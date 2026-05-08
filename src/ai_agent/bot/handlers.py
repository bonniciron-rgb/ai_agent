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
    """Stateless handler collection.  Inject *store* at construction time.

    Parameters
    ----------
    store:
        DB-backed or fake DecisionStore for recording approve/reject decisions.
    order_executor:
        Optional callable ``(proposal_id: int) -> None`` invoked immediately
        after a proposal is approved.  Pass ``None`` in dry-run / test mode.
    """

    def __init__(
        self,
        store: DecisionStore,
        order_executor: object | None = None,
    ) -> None:
        self._store = store
        self._order_executor = order_executor  # callable(proposal_id) -> None | Order

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

        if action == "approve" and self._order_executor is not None:
            try:
                self._order_executor(proposal_id)
                logger.info("Order submitted for proposal #%d", proposal_id)
            except Exception as exc:
                logger.warning("Order execution failed for proposal #%d: %s", proposal_id, exc)

        msg = decision_message(action, proposal_id, symbol)

        if action == EDIT:
            await query.edit_message_text(msg)
        else:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.edit_message_text(msg)

    async def handle_halt(self, update: object, context: object) -> None:
        """/halt — set the DB-backed halt flag.  The daily cron checks it before each run."""
        try:
            from telegram import Update
        except ImportError:
            return

        if not isinstance(update, Update) or update.message is None:
            return

        try:
            from ai_agent.db.settings_store import set_trading_halted

            user = update.message.from_user
            decided_by = (
                f"@{user.username}"
                if user and user.username
                else str(user.id if user else "system")
            )
            set_trading_halted(True, updated_by=decided_by)
            await update.message.reply_text(
                "🛑 Trading halted. Use /resume to restart.",
            )
        except Exception as exc:
            logger.exception("Failed to set halt flag")
            await update.message.reply_text(f"⚠️ Could not halt: {exc}")

    async def handle_resume(self, update: object, context: object) -> None:
        """/resume — clear the halt flag so the next cron run will execute."""
        try:
            from telegram import Update
        except ImportError:
            return

        if not isinstance(update, Update) or update.message is None:
            return

        try:
            from ai_agent.db.settings_store import set_trading_halted

            user = update.message.from_user
            decided_by = (
                f"@{user.username}"
                if user and user.username
                else str(user.id if user else "system")
            )
            set_trading_halted(False, updated_by=decided_by)
            await update.message.reply_text("✅ Trading resumed. Next cron run will execute.")
        except Exception as exc:
            logger.exception("Failed to clear halt flag")
            await update.message.reply_text(f"⚠️ Could not resume: {exc}")

    async def handle_status(self, update: object, context: object) -> None:
        """/status — show halt state and pending proposal count."""
        try:
            from telegram import Update
        except ImportError:
            return

        if not isinstance(update, Update) or update.message is None:
            return

        try:
            from ai_agent.db.settings_store import is_trading_halted

            halted = is_trading_halted()
            state = "🛑 HALTED" if halted else "✅ running"
            await update.message.reply_text(f"Status: {state}")
        except Exception as exc:
            await update.message.reply_text(f"Status check failed: {exc}")

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
