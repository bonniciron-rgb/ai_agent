"""Tests for Telegram message formatting helpers."""

from decimal import Decimal

import pytest

from ai_agent.bot.formatting import (
    APPROVE,
    DEFER,
    EDIT,
    REJECT,
    approval_keyboard,
    decision_message,
    parse_callback,
    proposal_message,
)


def test_proposal_message_contains_symbol_and_side() -> None:
    msg = proposal_message(
        proposal_id=1,
        symbol="AAPL",
        side="buy",
        quantity=10,
        limit_price="175.00",
        stop_price="168.00",
        rationale="Strong uptrend.",
        confidence="high",
    )
    assert "AAPL" in msg
    assert "BUY" in msg
    assert "175.00" in msg
    assert "168.00" in msg
    assert "Strong uptrend." in msg


def test_proposal_message_no_stop_price() -> None:
    msg = proposal_message(
        proposal_id=2,
        symbol="MSFT",
        side="sell",
        quantity=5,
        limit_price="310.00",
        stop_price=None,
        rationale="Bearish breakdown.",
        confidence="medium",
    )
    assert "Stop" not in msg
    assert "MSFT" in msg


def test_proposal_message_singular_share() -> None:
    msg = proposal_message(
        proposal_id=3,
        symbol="X",
        side="buy",
        quantity=1,
        limit_price="50.00",
        stop_price=None,
        rationale=".",
        confidence="low",
    )
    assert "share" in msg
    assert "shares" not in msg


def test_proposal_message_plural_shares() -> None:
    msg = proposal_message(
        proposal_id=4,
        symbol="X",
        side="buy",
        quantity=3,
        limit_price="50.00",
        stop_price=None,
        rationale=".",
        confidence="low",
    )
    assert "shares" in msg


def test_proposal_message_fractional_quantity() -> None:
    # A full exit of a fractional holding must render the real quantity.
    msg = proposal_message(
        proposal_id=9,
        symbol="NVDD",
        side="sell",
        quantity=Decimal("0.8"),
        limit_price="31.40",
        stop_price=None,
        rationale="Full exit of the position.",
        confidence="medium",
    )
    assert "0.8 share" in msg
    assert "1 share" not in msg


def test_proposal_message_whole_quantity_has_no_trailing_zeros() -> None:
    msg = proposal_message(
        proposal_id=10,
        symbol="AAPL",
        side="sell",
        quantity=Decimal("3.0"),
        limit_price="180.00",
        stop_price=None,
        rationale=".",
        confidence="low",
    )
    assert "3 shares" in msg
    assert "3.0" not in msg


def test_approval_keyboard_has_four_buttons() -> None:
    kb = approval_keyboard(42)
    buttons = [btn for row in kb for btn in row]
    assert len(buttons) == 4
    callback_actions = {btn["callback_data"].split(":")[0] for btn in buttons}
    assert callback_actions == {APPROVE, REJECT, DEFER, EDIT}


def test_approval_keyboard_encodes_proposal_id() -> None:
    kb = approval_keyboard(99)
    for row in kb:
        for btn in row:
            assert btn["callback_data"].endswith(":99")


def test_parse_callback_valid() -> None:
    action, pid = parse_callback("approve:42")
    assert action == APPROVE
    assert pid == 42


def test_parse_callback_all_actions() -> None:
    for action in (APPROVE, REJECT, DEFER, EDIT):
        a, pid = parse_callback(f"{action}:1")
        assert a == action
        assert pid == 1


def test_parse_callback_invalid_format_raises() -> None:
    with pytest.raises(ValueError):
        parse_callback("no_colon_here")


def test_parse_callback_unknown_action_raises() -> None:
    with pytest.raises(ValueError, match="Unknown action"):
        parse_callback("explode:1")


def test_parse_callback_non_integer_id_raises() -> None:
    with pytest.raises(ValueError):
        parse_callback("approve:abc")


def test_decision_message_approve() -> None:
    msg = decision_message(APPROVE, 5, "AAPL")
    assert "approved" in msg.lower()
    assert "AAPL" in msg
    assert "#5" in msg


def test_decision_message_reject() -> None:
    msg = decision_message(REJECT, 6, "MSFT")
    assert "rejected" in msg.lower()


def test_decision_message_defer() -> None:
    msg = decision_message(DEFER, 7, "GOOG")
    assert "defer" in msg.lower()


def test_decision_message_edit() -> None:
    msg = decision_message(EDIT, 8, "TSLA")
    assert "edit" in msg.lower() or "reply" in msg.lower() or "price" in msg.lower()
