#!/usr/bin/env python3
import json
import http.server
import socketserver
from pathlib import Path
from urllib.parse import urlparse

from .config import load_config
from .inventory import collect_inventory

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

    def send_bytes(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status=200):
        self.send_bytes(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

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

        if path == "/" or path == "":
            path = "/index.html"
        file_path = (BASE / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(BASE.resolve())) or not file_path.exists():
            self.send_bytes(404, b"Not found", "text/plain")
            return
        self.send_bytes(200, file_path.read_bytes(), CONTENT_TYPES.get(file_path.suffix, "application/octet-stream"))


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    httpd.serve_forever()
