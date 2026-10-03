"""Minimal local Nimbus HTTP API used by NEO wall controllers."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import subprocess
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from config import (
    KEY_FILE,
    KNOWN_DEVICES_FILE,
    LOCAL_IP,
    LOCAL_USER_ID,
    NEO_MQTT_PORT,
    NIMBUS_ACCOUNT_DELAY_IP,
    NIMBUS_ACCOUNT_DELAY_SECONDS,
    NIMBUS_SYNTHETIC_JWT,
)

_LOGGER = logging.getLogger("actronneo-localcloud.nimbus")

_NAME_CLAIM = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"
_NAME_ID_CLAIM = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"
_ROLE_CLAIM = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"
_NIMBUS_ISSUER = "actronair.com.au"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_kid() -> str:
    """Return a stable local key identifier without exposing key material."""
    try:
        return hashlib.sha1(Path(KEY_FILE).read_bytes()).hexdigest().upper()
    except OSError:
        return "LOCAL-NEO-JWT"


def _known_session_name(serial: str) -> str:
    if not serial:
        return "LOCAL NEO"
    try:
        if KNOWN_DEVICES_FILE.exists():
            data = json.loads(KNOWN_DEVICES_FILE.read_text())
            record = data.get(serial.lower()) if isinstance(data, dict) else None
            if isinstance(record, dict):
                name = str(record.get("name", "")).strip()
                if name:
                    return name
    except Exception as exc:
        _LOGGER.debug("Could not read known device name for synthetic JWT: %s", exc)
    return serial.upper()


def _fallback_pairing_id(serial: str) -> str:
    digest = hashlib.sha256(f"{LOCAL_USER_ID}:{serial}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def _sign_rs256(header: dict[str, Any], claims: dict[str, Any]) -> str:
    encoded_header = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_claims = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")

    proc = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", KEY_FILE],
        input=signing_input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"openssl RS256 signing failed: {stderr or proc.returncode}")

    return f"{encoded_header}.{encoded_claims}.{_b64url(proc.stdout)}"


class NimbusHandler(BaseHTTPRequestHandler):
    server_version = "ActronNEOLocalCloud/1.0"

    def _client_ip(self) -> str:
        # Nimbus is only exposed through the local nginx reverse proxy. nginx
        # supplies the real NEO source address so diagnostics can target one
        # controller without affecting the others.
        return self.headers.get("X-Real-IP", self.client_address[0]).strip()

    def _neo_serial(self) -> str:
        # Real NEO requests identify the controller in the User-Agent, for
        # example NEO-V2.6.2.5-26D03211.
        user_agent = self.headers.get("User-Agent", "")
        match = re.search(r"NEO-V[^\s-]+-([A-Za-z0-9]+)", user_agent, re.IGNORECASE)
        return match.group(1).lower() if match else ""

    def log_message(self, fmt: str, *args: Any) -> None:
        _LOGGER.info("%s - %s", self._client_ip(), fmt % args)

    def _send_json(self, obj: Any, status: int = 200) -> None:
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _synthetic_oauth_jwt(self, refresh_token: str) -> str:
        serial = self._neo_serial()
        session_name = _known_session_name(serial)
        pairing_id = refresh_token or _fallback_pairing_id(serial)
        now = int(time.time())

        # Reproduce the claim names/types observed in a real Nimbus refresh-token
        # response. Values remain local/synthetic; no Actron signing key or cloud
        # credential is stored in the add-on.
        claims: dict[str, Any] = {
            _NAME_CLAIM: "neo@local.invalid",
            _NAME_ID_CLAIM: LOCAL_USER_ID,
            "nxgen/pairing-id": pairing_id,
            "nxgen/sesison-name": session_name,  # Nimbus uses this spelling.
            _ROLE_CLAIM: ["paired-mwc", "validated-user"],
            "nxgen/wc-serial": serial.upper(),
            "nxgen/no-log": "true",
            "nbf": now,
            "exp": now + 259200,
            "iss": _NIMBUS_ISSUER,
            "aud": _NIMBUS_ISSUER,
            "acl": [
                {
                    "permission": "allow",
                    "action": "subscribe",
                    "topic": f"actron-cloud/{LOCAL_USER_ID}/#",
                },
                {
                    "permission": "allow",
                    "action": "publish",
                    "topic": f"actron-cloud/{LOCAL_USER_ID}/#",
                },
                {
                    "permission": "deny",
                    "action": "subscribe",
                    "topic": "actron-cloud/#",
                },
                {
                    "permission": "deny",
                    "action": "publish",
                    "topic": "actron-cloud/#",
                },
            ],
        }
        header = {"alg": "RS256", "typ": "JWT", "kid": _jwt_kid()}
        token = _sign_rs256(header, claims)

        _LOGGER.info(
            "Nimbus diagnostic: issued synthetic RS256 OAuth JWT for %s "
            "(session=%r, claims=%d, acl=%d, pairing-id=%s, token-bytes=%d)",
            serial or self._client_ip(),
            session_name,
            len(claims),
            len(claims["acl"]),
            "refresh-token" if refresh_token else "local-fallback",
            len(token),
        )
        return token

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        path = self.path.split("?", 1)[0]

        if path == "/api/v0/oauth/token":
            if NIMBUS_SYNTHETIC_JWT:
                try:
                    form = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
                    grant_type = (form.get("grant_type") or [""])[0]
                    refresh_token = (form.get("refresh_token") or [""])[0]
                    if grant_type and grant_type != "refresh_token":
                        _LOGGER.warning(
                            "Nimbus synthetic JWT diagnostic received unexpected grant_type=%r",
                            grant_type,
                        )
                    access_token = self._synthetic_oauth_jwt(refresh_token)
                except Exception as exc:
                    _LOGGER.exception("Could not generate synthetic Nimbus OAuth JWT: %s", exc)
                    self._send_json({"message": "Local OAuth JWT generation failed"}, 500)
                    return
            else:
                access_token = "LOCAL-NEO-TOKEN"

            self._send_json(
                {
                    "access_token": access_token,
                    "token_type": "bearer",
                    "expires_in": 259199,
                }
            )
            return

        self._send_json({"message": "Not found"}, 404)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path == "/api/v0/messaging/connection/details":
            now = datetime.now(timezone.utc)
            self._send_json(
                {
                    "Endpoint": LOCAL_IP,
                    "Port": str(NEO_MQTT_PORT),
                    "Protocol": "TLS",
                    "WcMinFwVersion": "2.5.x;3.5.x",
                    "Time": now.strftime("%-m/%-d/%Y %-I:%M:%S %p"),
                    "UserId": LOCAL_USER_ID,
                    "OptOutOfLogging": True,
                }
            )
            return

        if path == "/api/v0/client/account":
            client_ip = self._client_ip()
            if (
                NIMBUS_ACCOUNT_DELAY_SECONDS > 0
                and NIMBUS_ACCOUNT_DELAY_IP
                and client_ip == NIMBUS_ACCOUNT_DELAY_IP
            ):
                _LOGGER.info(
                    "Nimbus diagnostic: /client/account received from %s; delaying response %ss",
                    client_ip,
                    NIMBUS_ACCOUNT_DELAY_SECONDS,
                )
                time.sleep(NIMBUS_ACCOUNT_DELAY_SECONDS)
                _LOGGER.info(
                    "Nimbus diagnostic: /client/account delay complete for %s; sending normal response",
                    client_ip,
                )

            # Match the real Nimbus account response structure captured from a
            # paired NEO. Account values remain local/synthetic; the experiment
            # changes only the HAL-style _links object that was previously {}.
            self._send_json(
                {
                    "id": LOCAL_USER_ID,
                    "email": "neo@local.invalid",
                    "emailConfirmed": True,
                    "fullName": "",
                    "address": "",
                    "suburb": "",
                    "state": "",
                    "country": "",
                    "postcode": "",
                    "_links": {
                        "self": {"href": "/api/v0/client/account"},
                        "change-email": {
                            "href": "/api/v0/client/account/change-email",
                            "title": "Change Email",
                        },
                        "change-password": {
                            "href": "/api/v0/client/account/change-password",
                            "title": "Change Password",
                        },
                        "update-details": {
                            "href": "/api/v0/client/account/update-details",
                            "title": "Update Details",
                        },
                        "register-account": {
                            "href": "/api/v0/client/account/register",
                            "title": "POST to create a new account, GET will return format of the object to fill out.",
                        },
                        "forgot-password": {
                            "href": "/api/v0/client/account/forgot-password",
                            "title": "Forgot Password",
                        },
                        "reset-password": {
                            "href": "/api/v0/client/account/reset-password",
                            "title": "Forgot Password",
                        },
                    },
                }
            )
            return

        if path.startswith("/api/v0/ota/target-device/"):
            self._send_json({"_links": None})
            return

        self._send_json({"message": "Not found"}, 404)


def run_nimbus() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8080), NimbusHandler)
    _LOGGER.info("Nimbus emulator listening on 127.0.0.1:8080")
    if NIMBUS_SYNTHETIC_JWT:
        _LOGGER.info(
            "Nimbus synthetic OAuth JWT diagnostic enabled: RS256 local signature, real Nimbus claim structure"
        )
    if NIMBUS_ACCOUNT_DELAY_SECONDS > 0 and NIMBUS_ACCOUNT_DELAY_IP:
        _LOGGER.info(
            "Nimbus account delay diagnostic enabled: target=%s delay=%ss",
            NIMBUS_ACCOUNT_DELAY_IP,
            NIMBUS_ACCOUNT_DELAY_SECONDS,
        )
    server.serve_forever()
