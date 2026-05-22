"""Format trade proposals as Telegram messages with inline approval buttons.

Each proposal gets a message like::

    📋 Trade Proposal #42
    🟢 AAPL · BUY 10 shares
    Limit: $175.00 | Stop: $168.00
    Conf: 🟢 high | Regime: trending_up

    Strong uptrend confirmed with ADX=28 and volume spike.
    RSI=55 — not overbought.

    🔗 https://dashboard.example.com/proposals/42
    [✅ Approve] [✏️ Edit] [❌ Reject] [⏭ Defer]

Callback data format: ``<action>:<proposal_id>``
Actions: approve, reject, defer, edit
"""

from __future__ import annotations

import os
import re
from decimal import Decimal

APPROVE = "approve"
REJECT = "reject"
DEFER = "defer"
EDIT = "edit"

ACTIONS = (APPROVE, REJECT, DEFER, EDIT)

# Traffic-light dots: green = high conviction, yellow = medium, red = low.
_CONFIDENCE_EMOJI = {"high": "🟢", "medium": "🟡", "low": "🔴"}
_SIDE_EMOJI = {"buy": "🟢", "sell": "🔴"}

# Sentence boundary for the rationale truncation.  We keep the first three
# sentences; anything longer gets a trailing ellipsis.  Markers: . ! ? followed
# by whitespace or end-of-string.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _truncate_sentences(text: str, max_sentences: int = 3) -> str:
    """Return the first `max_sentences` sentences of `text`, with `…` if truncated."""
    text = (text or "").strip()
    if not text:
        return ""
    parts = _SENTENCE_RE.split(text)
    if len(parts) <= max_sentences:
        return text
    return " ".join(parts[:max_sentences]).rstrip() + " …"


def _format_quantity(quantity: object) -> tuple[str, str]:
    """Return ``(display_text, plural_suffix)`` for a share quantity.

    Renders fractional positions honestly (``0.8``) and strips misleading
    trailing zeros from whole-share counts.
    """
    qty = Decimal(str(quantity))
    integral = qty.to_integral_value()
    text = str(integral) if qty == integral else str(qty.normalize())
    return text, ("" if qty == 1 else "s")


def _resolve_dashboard_base_url() -> str | None:
    """Return the dashboard base URL (no trailing slash), or None if unknown.

    Matches the resolution order used by ``ai_agent.bot.handlers``:
      1. ``DASHBOARD_BASE_URL`` env var, if it parses as ``http(s)://``.
      2. ``https://{VERCEL_URL}`` if VERCEL_URL is set.
      3. None.
    """
    raw = os.environ.get("DASHBOARD_BASE_URL", "").strip().rstrip("/")
    if raw.startswith(("http://", "https://")):
        return raw
    vercel_url = os.environ.get("VERCEL_URL", "").strip().rstrip("/")
    if vercel_url:
        return f"https://{vercel_url}"
    return None


def proposal_message(
    proposal_id: int,
    symbol: str,
    side: str,
    quantity: Decimal | int | str,
    limit_price: str,
    stop_price: str | None,
    rationale: str,
    confidence: str,
    regime: str | None = None,
) -> str:
    """Return the plain-text body of the Telegram proposal message.

    Includes a trimmed rationale (first 2-3 sentences), traffic-light
    confidence emoji, and — when ``DASHBOARD_BASE_URL`` (or ``VERCEL_URL``)
    is set — a deep link to the proposal-detail page on the dashboard.
    """
    side_em = _SIDE_EMOJI.get(side.lower(), "")
    conf_em = _CONFIDENCE_EMOJI.get(confidence.lower(), "")
    stop_str = f" | Stop: ${stop_price}" if stop_price else ""
    regime_str = f" | Regime: {regime}" if regime else ""
    short_rationale = _truncate_sentences(rationale, 3)
    qty_str, qty_suffix = _format_quantity(quantity)

    lines = [
        f"📋 <b>Trade Proposal #{proposal_id}</b>",
        f"{side_em} <b>{symbol}</b> · {side.upper()} {qty_str} share{qty_suffix}",
        f"Limit: ${limit_price}{stop_str}",
        f"Conf: {conf_em} {confidence}{regime_str}",
        "",
        short_rationale,
    ]

    base = _resolve_dashboard_base_url()
    if base:
        lines.append("")
        lines.append(f"🔗 {base}/proposals/{proposal_id}")

    return "\n".join(lines)


def approval_keyboard(proposal_id: int) -> list[list[dict]]:
    """Return an inline keyboard layout for the approval flow.

    Returns a list-of-rows in python-telegram-bot InlineKeyboardButton dict
    format so callers can pass it directly to ``InlineKeyboardMarkup``.
    """
    return [
        [
            {"text": "✅ Approve", "callback_data": f"{APPROVE}:{proposal_id}"},
            {"text": "✏️ Edit", "callback_data": f"{EDIT}:{proposal_id}"},
        ],
        [
            {"text": "❌ Reject", "callback_data": f"{REJECT}:{proposal_id}"},
            {"text": "⏭ Defer", "callback_data": f"{DEFER}:{proposal_id}"},
        ],
    ]


def parse_callback(data: str) -> tuple[str, int]:
    """Parse ``<action>:<proposal_id>`` callback data.

    Returns ``(action, proposal_id)`` or raises ``ValueError`` on bad format.
    """
    parts = data.split(":", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid callback data: {data!r}")
    action, pid_str = parts
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r} in callback {data!r}")
    try:
        proposal_id = int(pid_str)
    except ValueError:
        raise ValueError(f"Non-integer proposal_id in callback {data!r}") from None
    return action, proposal_id


def decision_message(action: str, proposal_id: int, symbol: str) -> str:
    """Return a short confirmation message after a decision is recorded."""
    messages = {
        APPROVE: f"✅ Proposal #{proposal_id} ({symbol}) approved — submitting order.",
        REJECT: f"❌ Proposal #{proposal_id} ({symbol}) rejected.",
        DEFER: f"⏭ Proposal #{proposal_id} ({symbol}) deferred to next session.",
        EDIT: f"✏️ Proposal #{proposal_id} ({symbol}) — reply with new limit price:",
    }
    return messages.get(action, f"Proposal #{proposal_id} updated.")
