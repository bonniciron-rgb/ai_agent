"""Vercel serverless entry point for the Telegram webhook.

Vercel's Python runtime requires a ``BaseHTTPRequestHandler`` subclass named
``handler`` (https://vercel.com/docs/functions/runtimes/python).  This file is
the adapter — all real logic lives in ``ai_agent.bot.webhook.handle``.

The wrapper:
1. Receives the POST body via ``self.rfile``
2. Forwards it to the async ``handle()`` function via ``asyncio.run()``
3. Writes the resulting status + JSON body back to the response
"""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler

from ai_agent.bot.webhook import handle as _handle


class _Request:
    """Minimal request shim mirroring the FastAPI/Starlette ``request.body()`` API."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else b""

        try:
            result = asyncio.run(_handle(_Request(body)))
        except Exception as exc:  # last-resort guard so a bug doesn't 500 silently
            self._write(500, {"ok": False, "error": str(exc)})
            return

        status = int(result.get("statusCode", 200))
        response_body = result.get("body", "")
        self._write(status, response_body)

    def do_GET(self) -> None:
        # Health check so the URL is pingable from a browser without a 404.
        self._write(200, {"ok": True, "service": "telegram_webhook"})

    def _write(self, status: int, body: dict | str | bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        if isinstance(body, dict):
            payload = json.dumps(body).encode()
        elif isinstance(body, str):
            payload = body.encode()
        else:
            payload = body
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
