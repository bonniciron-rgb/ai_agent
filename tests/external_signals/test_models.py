"""Tests for ParsedSignal and RawMessage Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ai_agent.external_signals.models import ParsedSignal, RawMessage

# ---------------------------------------------------------------------------
# RawMessage
# ---------------------------------------------------------------------------


def test_raw_message_roundtrip() -> None:
    msg = RawMessage(
        message_id=42,
        channel="@JdubTrades_Telegram",
        posted_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        text="AAPL looking bullish here",
    )
    assert msg.message_id == 42
    assert msg.channel == "@JdubTrades_Telegram"
    assert msg.text == "AAPL looking bullish here"


# ---------------------------------------------------------------------------
# ParsedSignal — valid cases
# ---------------------------------------------------------------------------


def test_parsed_signal_uppercases_symbol() -> None:
    sig = ParsedSignal(symbol="aapl", side="buy")
    assert sig.symbol == "AAPL"


def test_parsed_signal_strips_whitespace() -> None:
    sig = ParsedSignal(symbol="  MSFT  ", side=" sell ")
    assert sig.symbol == "MSFT"
    assert sig.side == "sell"


def test_parsed_signal_full() -> None:
    sig = ParsedSignal(
        symbol="NVDA",
        side="buy",
        entry_price=Decimal("900"),
        stop_price=Decimal("875"),
        target_price=Decimal("950"),
        conviction="high",
        notes="Breakout on earnings",
    )
    assert sig.symbol == "NVDA"
    assert sig.entry_price == Decimal("900")
    assert sig.conviction == "high"


def test_parsed_signal_watch_side() -> None:
    sig = ParsedSignal(symbol="TSLA", side="WATCH")
    assert sig.side == "watch"


def test_parsed_signal_optional_fields_none() -> None:
    sig = ParsedSignal(symbol="AMD", side="buy")
    assert sig.entry_price is None
    assert sig.stop_price is None
    assert sig.conviction is None
    assert sig.notes is None


# ---------------------------------------------------------------------------
# ParsedSignal — validation errors
# ---------------------------------------------------------------------------


def test_parsed_signal_invalid_side() -> None:
    with pytest.raises(Exception):
        ParsedSignal(symbol="AAPL", side="short")


def test_parsed_signal_invalid_conviction() -> None:
    with pytest.raises(Exception):
        ParsedSignal(symbol="AAPL", side="buy", conviction="super-high")


def test_parsed_signal_conviction_normalised() -> None:
    sig = ParsedSignal(symbol="AAPL", side="buy", conviction="HIGH")
    assert sig.conviction == "high"
