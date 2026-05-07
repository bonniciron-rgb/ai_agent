"""Send the daily proposal digest to the Telegram group.

Called by the GitHub Actions cron job after the agent generates proposals.
Sends one message per proposal with inline approval buttons.
"""

from __future__ import annotations

import logging

from ai_agent.bot.formatting import approval_keyboard, proposal_message

logger = logging.getLogger(__name__)


async def send_proposals(
    bot,  # telegram.Bot instance
    chat_id: str,
    proposals: list[dict],
) -> list[int]:
    """Send each proposal as an inline-keyboard message.

    Parameters
    ----------
    bot:
        A ``telegram.Bot`` instance.
    chat_id:
        Target group/channel chat id.
    proposals:
        List of dicts with keys: id, symbol, side, quantity, limit_price,
        stop_price (optional), rationale, confidence, regime (optional).

    Returns
    -------
    List of sent message IDs.
    """
    sent_ids: list[int] = []

    if not proposals:
        await bot.send_message(
            chat_id=chat_id,
            text="📭 No trade proposals today — no signals met the criteria.",
        )
        return sent_ids

    for p in proposals:
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        except ImportError:
            logger.error("python-telegram-bot not installed")
            break

        pid = p["id"]
        keyboard_rows = approval_keyboard(pid)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(**btn) for btn in row] for row in keyboard_rows]
        )

        text = proposal_message(
            proposal_id=pid,
            symbol=p["symbol"],
            side=p["side"],
            quantity=p["quantity"],
            limit_price=str(p.get("limit_price", "?")),
            stop_price=str(p["stop_price"]) if p.get("stop_price") else None,
            rationale=p.get("rationale", ""),
            confidence=p.get("confidence", "medium"),
            regime=p.get("regime"),
        )

        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        sent_ids.append(msg.message_id)
        logger.info("Sent proposal #%d for %s (msg_id=%d)", pid, p["symbol"], msg.message_id)

    return sent_ids
