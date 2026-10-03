"""Minimal local Nimbus HTTP API used by NEO wall controllers."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from config import (
    LOCAL_IP,
    LOCAL_USER_ID,
    NEO_MQTT_PORT,
    NIMBUS_ACCOUNT_DELAY_IP,
    NIMBUS_ACCOUNT_DELAY_SECONDS,
)

_LOGGER = logging.getLogger("actronneo-localcloud.nimbus")


class NimbusHandler(BaseHTTPRequestHandler):
    server_version = "ActronNEOLocalCloud/1.0"

    def _client_ip(self) -> str:
        # Nimbus is only exposed through the local nginx reverse proxy. nginx
        # supplies the real NEO source address so diagnostics can target one
        # controller without affecting the others.
        return self.headers.get("X-Real-IP", self.client_address[0]).strip()

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

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length:
            self.rfile.read(length)

        if self.path == "/api/v0/oauth/token":
            self._send_json(
                {
                    "access_token": "LOCAL-NEO-TOKEN",
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
                    "_links": {},
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
    if NIMBUS_ACCOUNT_DELAY_SECONDS > 0 and NIMBUS_ACCOUNT_DELAY_IP:
        _LOGGER.info(
            "Nimbus account delay diagnostic enabled: target=%s delay=%ss",
            NIMBUS_ACCOUNT_DELAY_IP,
            NIMBUS_ACCOUNT_DELAY_SECONDS,
        )
    server.serve_forever()
