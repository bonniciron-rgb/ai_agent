"""Minimal Vercel handler for diagnosing the 404.

If this file is reachable at /api/telegram_webhook, the function is being
deployed and Vercel's Python runtime is dispatching correctly.  We can
then re-introduce the ai_agent imports incrementally.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._write(200, {"ok": True, "stage": "minimal", "method": "GET"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        _ = self.rfile.read(length) if length > 0 else b""
        self._write(200, {"ok": True, "stage": "minimal", "method": "POST"})

    def _write(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
