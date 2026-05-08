"""Vercel serverless webhook entry point for the Telegram bot.

Deploy as ``api/telegram_webhook.py`` (Vercel Python runtime).
Telegram sends POST requests here for every update.

Environment variables required:
  TELEGRAM_BOT_TOKEN   — set in Vercel project settings
  TELEGRAM_CHAT_ID     — allowed chat id for security check
  DATABASE_URL         — Neon Postgres connection string

The Application is built once per cold start and reused across invocations
within the same Vercel function instance (warm Lambda).

Registration (run once after deploy):
  curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=<VERCEL_URL>/api/telegram_webhook"
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _build_application():  # type: ignore[return]
    """Construct the PTB Application (lazy import so Vercel cold-start is fast)."""
    try:
        from telegram.ext import Application, CallbackQueryHandler, CommandHandler
    except ImportError as exc:
        raise RuntimeError(
            "python-telegram-bot not installed — add 'bot' extra to requirements"
        ) from exc

    from ai_agent.bot.handlers import BotHandlers
    from ai_agent.bot.store import DbDecisionStore
    from ai_agent.loop.order_executor import submit_order

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    store = DbDecisionStore()

    # Build a live T212 client if credentials are present; None = no-op (dry-run)
    _order_executor = None
    t212_api_key = os.environ.get("T212_API_KEY", "")
    t212_base_url = os.environ.get("T212_BASE_URL", "https://demo.trading212.com")
    if t212_api_key:
        from ai_agent.broker.t212_client import T212Client

        _t212 = T212Client(api_key=t212_api_key, base_url=t212_base_url)
        _order_executor = lambda pid: submit_order(pid, _t212)  # noqa: E731

    handlers = BotHandlers(store=store, order_executor=_order_executor)

    app = (
        Application.builder()
        .token(token)
        .updater(None)  # webhook mode — no polling
        .build()
    )
    app.add_handler(CallbackQueryHandler(handlers.handle_callback))
    app.add_handler(CommandHandler("halt", handlers.handle_halt))
    app.add_handler(CommandHandler("resume", handlers.handle_resume))
    app.add_handler(CommandHandler("status", handlers.handle_status))
    app.add_handler(CommandHandler("config", handlers.handle_config))
    return app


_app = None


async def handle(request: Any) -> Any:
    """Vercel async handler called on each HTTP request.

    Compatible with Vercel's Python runtime (ASGI / BaseHTTPRequestHandler).
    For local testing use ``python -m ai_agent.bot.webhook``.
    """
    global _app

    # Parse body
    try:
        body = await request.body() if hasattr(request, "body") else request.get_data()
        if isinstance(body, bytes):
            body = body.decode()
        update_data = json.loads(body)
    except Exception as exc:
        logger.warning("Failed to parse Telegram update: %s", exc)
        return _response(400, {"ok": False, "error": "bad request"})

    # Security: only accept updates from the configured chat
    allowed_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if allowed_chat:
        chat_id = _extract_chat_id(update_data)
        if chat_id and str(chat_id) != str(allowed_chat):
            logger.warning("Update from unknown chat %s — ignoring", chat_id)
            return _response(200, {"ok": True})

    # Build app on first call
    if _app is None:
        _app = _build_application()
        await _app.initialize()

    try:
        from telegram import Update
    except ImportError:
        return _response(500, {"ok": False, "error": "telegram not installed"})

    update = Update.de_json(update_data, _app.bot)
    await _app.process_update(update)
    return _response(200, {"ok": True})


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "body": json.dumps(body)}


def _extract_chat_id(data: dict) -> int | None:
    for key in ("message", "callback_query", "edited_message"):
        obj = data.get(key)
        if obj and "chat" in obj:
            return obj["chat"].get("id")
        if obj and "message" in obj and "chat" in obj["message"]:
            return obj["message"]["chat"].get("id")
    return None
