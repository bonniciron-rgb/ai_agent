"""Format trade proposals as Telegram messages with inline approval buttons.

Each proposal gets a message like:

  📋 Trade Proposal #42
  AAPL · BUY 10 shares
  Limit: $175.00 | Stop: $168.00
  Regime: trending_up | Confidence: high

  Strong uptrend confirmed with ADX=28 and volume spike.
  RSI=55 — not overbought.

  [✅ Approve] [✏️ Edit] [❌ Reject] [⏭ Defer]

Callback data format: ``<action>:<proposal_id>``
Actions: approve, reject, defer, edit
"""

from __future__ import annotations

APPROVE = "approve"
REJECT = "reject"
DEFER = "defer"
EDIT = "edit"

ACTIONS = (APPROVE, REJECT, DEFER, EDIT)

_CONFIDENCE_EMOJI = {"high": "🔥", "medium": "⚡", "low": "🌤"}
_SIDE_EMOJI = {"buy": "🟢", "sell": "🔴"}


def proposal_message(
    proposal_id: int,
    symbol: str,
    side: str,
    quantity: int,
    limit_price: str,
    stop_price: str | None,
    rationale: str,
    confidence: str,
    regime: str | None = None,
) -> str:
    """Return the plain-text body of the Telegram proposal message."""
    side_em = _SIDE_EMOJI.get(side.lower(), "")
    conf_em = _CONFIDENCE_EMOJI.get(confidence.lower(), "")
    stop_str = f" | Stop: ${stop_price}" if stop_price else ""
    regime_str = f" | Regime: {regime}" if regime else ""

    return (
        f"📋 <b>Trade Proposal #{proposal_id}</b>\n"
        f"{side_em} <b>{symbol}</b> · {side.upper()} {quantity} share{'s' if quantity != 1 else ''}\n"
        f"Limit: ${limit_price}{stop_str}\n"
        f"{conf_em} Confidence: {confidence}{regime_str}\n"
        f"\n"
        f"{rationale}"
    )


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
