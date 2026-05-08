"""Vercel serverless entry point for the Telegram webhook.

Vercel's Python runtime requires a ``BaseHTTPRequestHandler`` subclass named
``handler``. All real logic lives in ``ai_agent.bot.webhook.handle``.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# vercel.json bundles src/ via includeFiles, but the package isn't pip-installed.
# Put src/ on sys.path so `import ai_agent.*` resolves.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Import lazily-captured: if the package import itself fails (missing deps,
# missing env vars referenced at module top-level, etc.), capture the error so
# we can return it in the response body instead of a generic 500.
_handle = None
_import_error: str | None = None
try:
    from ai_agent.bot.webhook import handle as _handle
except Exception:
    _import_error = traceback.format_exc()
    print("=" * 60, file=sys.stderr)
    print("FATAL: failed to import ai_agent.bot.webhook", file=sys.stderr)
    print(_import_error, file=sys.stderr)
    print("=" * 60, file=sys.stderr)


class _Request:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else b""

        if _handle is None:
            self._write(500, {"ok": False, "stage": "import", "error": _import_error})
            return

        try:
            result = asyncio.run(_handle(_Request(body)))
        except Exception as exc:
            tb = traceback.format_exc()
            print("=" * 60, file=sys.stderr)
            print(f"WEBHOOK CRASH: {exc!r}", file=sys.stderr)
            print(tb, file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            self._write(500, {"ok": False, "stage": "runtime", "error": str(exc), "traceback": tb})
            return

        status = int(result.get("statusCode", 200))
        response_body = result.get("body", "")
        self._write(status, response_body)

    def do_GET(self) -> None:
        # Surface import status on the GET health check too.
        if _handle is None:
            self._write(500, {"ok": False, "stage": "import", "error": _import_error})
            return
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
