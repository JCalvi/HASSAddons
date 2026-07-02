#!/usr/bin/env python3
import json
import http.server
import socketserver
from pathlib import Path
from urllib.parse import urlparse

from .config import load_config, save_runtime_config
from .inventory import collect_inventory
from .setup import key_status, ensure_key, install_keys, test_connections, configured_devices, save_devices_from_payload
from .steering import get_preferences, save_preferences, run_steering_once, start_steering_loop
from .mqtt import start_mqtt_loop, get_mqtt_status

PORT = 8090
BASE = Path("/app/web")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status=200):
        self.send_bytes(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def safe_config(self):
        cfg = load_config()
        safe = {k: v for k, v in cfg.items() if k != "password"}
        safe["devices"] = configured_devices(cfg)
        safe["preferences"] = get_preferences(cfg)
        safe["steering"] = {
            "enabled": cfg.get("steering_enabled", False),
            "interval_minutes": cfg.get("steering_interval_minutes", 10),
            "cooldown_minutes": cfg.get("steering_cooldown_minutes", 30),
        }
        safe["mqtt_status"] = get_mqtt_status()
        return safe

    def find_device_row(self, payload):
        selector_ip = str(payload.get("ip") or "").strip().lower()
        selector_mac = str(payload.get("mac") or "").strip().lower()
        selector_host = str(payload.get("host") or payload.get("name") or "").strip().lower()
        rows = collect_inventory(load_config())
        for row in rows:
            if selector_ip and str(row.get("ip") or "").lower() == selector_ip:
                return row
            if selector_mac and str(row.get("mac") or "").lower() == selector_mac:
                return row
            if selector_host and str(row.get("host") or "").lower() == selector_host:
                return row
        return None



    def steer_all_devices(self):
        cfg = load_config()
        rows = collect_inventory(cfg)
        results = []
        skipped_no_pref = 0
        skipped_not_wifi = 0
        already_correct = 0
        targets = []
        for row in rows:
            pref = row.get("preferred_ap") or "Auto"
            if not pref or pref == "Auto":
                skipped_no_pref += 1
                continue
            if row.get("status") != "online" or not row.get("mac") or not row.get("ap"):
                skipped_not_wifi += 1
                continue
            if row.get("ap") == pref:
                already_correct += 1
                results.append({"ok": True, "skipped": True, "message": "Already on preferred AP.", "device": row.get("mac") or row.get("ip") or row.get("host"), "host": row.get("host"), "current_ap": row.get("ap"), "preferred_ap": pref})
                continue
            targets.append(row)
        for row in targets:
            r = run_steering_once(row)
            if isinstance(r, list):
                results.extend(r)
            else:
                results.append(r)
        steered = len([r for r in results if r.get("ok") and not r.get("skipped")])
        failed = len([r for r in results if not r.get("ok")])
        return {"ok": failed == 0, "mode": "all", "total_devices": len(rows), "requested": len(targets), "steered": steered, "already_correct": already_correct, "skipped_no_preferred_ap": skipped_no_pref, "skipped_not_live_wifi": skipped_not_wifi, "failed": failed, "results": results}

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/api/refresh", "/network.json"}:
            try:
                cfg = load_config()
                rows = collect_inventory(cfg)
                self.send_json({"ok": True, "devices": rows})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc), "devices": []}, status=500)
            return

        if path == "/api/config":
            self.send_json({"ok": True, "config": self.safe_config(), "key": key_status()})
            return

        if path == "/api/ssh/test":
            try:
                self.send_json({"ok": True, "results": test_connections()})
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc), "results": []}, status=500)
            return

        if path == "/" or path == "":
            path = "/index.html"
        file_path = (BASE / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(BASE.resolve())) or not file_path.exists():
            self.send_bytes(404, b"Not found", "text/plain")
            return
        self.send_bytes(200, file_path.read_bytes(), CONTENT_TYPES.get(file_path.suffix, "application/octet-stream"))

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/config":
                if payload.get("devices") is not None:
                    cfg = save_devices_from_payload(payload)
                else:
                    allowed = {"piholes", "access_points", "ssh_user", "ping_workers", "ping_timeout", "tcp_probe", "tcp_ports", "steering_enabled", "steering_interval_minutes", "steering_cooldown_minutes"}
                    save_runtime_config({k: v for k, v in payload.items() if k in allowed})
                    cfg = load_config()
                self.send_json({"ok": True, "config": self.safe_config(), "key": key_status()})
                return
            if path == "/api/ssh/generate":
                self.send_json({"ok": True, "key": ensure_key(load_config(), payload.get("ssh_key_path"))})
                return
            if path in {"/api/ssh/install", "/api/ssh/install_all", "/api/ssh/install_one"}:
                self.send_json({"ok": True, "results": install_keys(payload), "key": key_status(), "config": self.safe_config()})
                return
            if path == "/api/ssh/test":
                self.send_json({"ok": True, "results": test_connections(payload)})
                return
            if path == "/api/preferences":
                cfg = save_preferences(payload)
                self.send_json({"ok": True, "config": self.safe_config()})
                return
            if path == "/api/steer":
                if payload.get("all") is True:
                    self.send_json(self.steer_all_devices())
                    return
                row = payload.get("device") or {}
                if not row:
                    row = self.find_device_row(payload) or {}
                if not row:
                    self.send_json({"ok": False, "error": "Device not found or not currently visible"}, status=404)
                    return
                results = run_steering_once(row)
                self.send_json({"ok": True, "results": results})
                return
            if path in {"/api/steer_device", "/api/service/steer"}:
                row = self.find_device_row(payload) or {}
                if not row:
                    self.send_json({"ok": False, "error": "Device not found or not currently visible"}, status=404)
                    return
                results = run_steering_once(row)
                self.send_json({"ok": True, "results": results})
                return
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)
            return
        self.send_json({"ok": False, "error": "Unknown endpoint"}, status=404)


start_steering_loop()
start_mqtt_loop()

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    httpd.serve_forever()
