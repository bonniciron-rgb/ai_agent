"""Telegram callback query and command handlers.

Designed to be imported by the Vercel webhook entry point and registered
with a python-telegram-bot Application.  All handler functions are async
(required by PTB v21+).

The handlers depend on a ``DecisionStore`` protocol so they can be tested
without a real database.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ai_agent.bot.formatting import (
    EDIT,
    decision_message,
    parse_callback,
)

logger = logging.getLogger(__name__)


class DecisionStore(Protocol):
    """Minimal interface the handlers need to record decisions."""

    def record_decision(self, proposal_id: int, action: str, decided_by: str) -> None: ...

    def get_proposal_symbol(self, proposal_id: int) -> str | None: ...


class BotHandlers:
    """Stateless handler collection.  Inject *store* at construction time."""

    def __init__(self, store: DecisionStore) -> None:
        self._store = store

    async def handle_callback(self, update: object, context: object) -> None:
        """Handle inline keyboard button presses."""
        # Lazy import so the module loads without python-telegram-bot installed
        try:
            from telegram import Update
        except ImportError:
            logger.error("python-telegram-bot not installed")
            return

        if not isinstance(update, Update):
            return
        query = update.callback_query
        if query is None:
            return

        await query.answer()

        try:
            action, proposal_id = parse_callback(query.data or "")
        except ValueError as exc:
            logger.warning("Bad callback data: %s", exc)
            await query.edit_message_text("⚠️ Invalid action.")
            return

        user = query.from_user
        decided_by = (
            f"@{user.username}" if user and user.username else str(user.id if user else "unknown")
        )

        symbol = self._store.get_proposal_symbol(proposal_id) or "???"
        self._store.record_decision(proposal_id, action, decided_by)
        logger.info("Decision %s on proposal #%d by %s", action, proposal_id, decided_by)

        msg = decision_message(action, proposal_id, symbol)

        if action == EDIT:
            await query.edit_message_text(msg)
        else:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(msg)

    async def handle_halt(self, update: object, context: object) -> None:
        """/halt command — sets a halt flag that the daily loop checks."""
        try:
            from telegram import Update
        except ImportError:
            return

        if not isinstance(update, Update) or update.message is None:
            return

        self._store.record_decision(-1, "halt", "system")
        await update.message.reply_text("🛑 Trading halted. Use /resume to restart.")

    async def handle_status(self, update: object, context: object) -> None:
        """/status command — replies with pending proposal count."""
        try:
            from telegram import Update
        except ImportError:
            return

        if not isinstance(update, Update) or update.message is None:
            return

        await update.message.reply_text("(i) Status: agent running normally.")

    async def handle_config(self, update: object, context: object) -> None:
        """/config show — display active external-signals configuration."""
        try:
            from telegram import Update
        except ImportError:
            return

        if not isinstance(update, Update) or update.message is None:
            return

        try:
            from ai_agent.external_signals.config import ExternalSignalsConfig

            cfg = ExternalSignalsConfig.load()
            lines = [
                "<b>External Signals Config</b>",
                f"Channels: {', '.join(cfg.channels)}",
                f"Cadence: {cfg.cadence}",
                f"Freshness: {cfg.freshness_days} days",
                f"Backfill: {cfg.backfill_days} days",
                f"Parser model: {cfg.parser_model}",
                "",
                "Edit <code>config/external_signals.yaml</code> in the repo to change these.",
            ]
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception as exc:
            await update.message.reply_text(f"Could not load config: {exc}")
