"""Magic-link JWT helpers for the dashboard /login flow.

The bot's /login command generates a short-lived signed token and sends
it to the user as a clickable link.  The Next.js dashboard verifies the
token at /auth/magic and issues a long-lived session cookie.

JWT format (HS256):
    header.payload.signature
where header   = {"alg":"HS256","typ":"JWT"}
      payload  = {"uid": "<chat_id>", "iat": <ts>, "exp": <ts>}
      signature = HMAC-SHA256(header.payload, secret)

Each part is base64url-encoded with padding stripped, matching the JWT spec
and `jose`'s decoder on the TypeScript side.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

_DEFAULT_TTL_SECONDS = 5 * 60  # 5 minutes


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _signing_secret() -> str:
    return os.environ.get("SESSION_SECRET") or os.environ["TELEGRAM_BOT_TOKEN"]


def issue_magic_token(
    chat_id: int | str,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    *,
    now: int | None = None,
) -> str:
    """Generate an HS256 JWT good for `ttl_seconds`."""
    issued = now if now is not None else int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "uid": str(chat_id),
        "iat": issued,
        "exp": issued + ttl_seconds,
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    body = f"{h}.{p}".encode()
    sig = hmac.new(_signing_secret().encode(), body, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def magic_link(base_url: str, chat_id: int | str) -> str:
    """Compose a complete clickable URL the user can tap from Telegram."""
    base = base_url.rstrip("/")
    return f"{base}/auth/magic?token={issue_magic_token(chat_id)}"
