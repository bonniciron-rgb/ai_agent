"""Tests for parse_message using a fake Anthropic client."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from ai_agent.external_signals.parser import parse_message

# ---------------------------------------------------------------------------
# Fake Anthropic client
# ---------------------------------------------------------------------------


def _fake_client(json_str: str):
    """Return a fake anthropic.Anthropic-like object that yields *json_str*."""

    class _FakeMessages:
        def create(self, **kwargs):
            block = SimpleNamespace(text=json_str)
            return SimpleNamespace(content=[block])

    client = SimpleNamespace(messages=_FakeMessages())
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_buy_signal() -> None:
    payload = '[{"symbol": "AAPL", "side": "buy", "entry_price": 185.0, "stop_price": 182.0, "conviction": "high"}]'
    signals = parse_message("AAPL breaking out...", client=_fake_client(payload))
    assert len(signals) == 1
    s = signals[0]
    assert s.symbol == "AAPL"
    assert s.side == "buy"
    assert s.entry_price == Decimal("185.0")
    assert s.stop_price == Decimal("182.0")
    assert s.conviction == "high"


def test_parse_empty_returns_empty_list() -> None:
    signals = parse_message("gm everyone 🚀", client=_fake_client("[]"))
    assert signals == []


def test_parse_watch_signal() -> None:
    payload = '[{"symbol": "TSLA", "side": "watch", "notes": "Watching for breakout"}]'
    signals = parse_message("Keep an eye on TSLA", client=_fake_client(payload))
    assert len(signals) == 1
    assert signals[0].side == "watch"
    assert signals[0].symbol == "TSLA"


def test_parse_multiple_signals() -> None:
    payload = (
        '[{"symbol": "MSFT", "side": "buy", "entry_price": 420.0}, '
        '{"symbol": "GOOG", "side": "sell", "entry_price": 175.0}]'
    )
    signals = parse_message("Two trades today", client=_fake_client(payload))
    assert len(signals) == 2
    syms = {s.symbol for s in signals}
    assert syms == {"MSFT", "GOOG"}


def test_parse_invalid_json_returns_empty() -> None:
    signals = parse_message("test", client=_fake_client("not json at all"))
    assert signals == []


def test_parse_non_list_json_returns_empty() -> None:
    signals = parse_message("test", client=_fake_client('{"symbol": "AAPL"}'))
    assert signals == []


def test_parse_skips_malformed_items() -> None:
    # Second item missing required "side"
    payload = '[{"symbol": "AAPL", "side": "buy"}, {"symbol": "MSFT"}]'
    signals = parse_message("test", client=_fake_client(payload))
    # Only the valid item should be returned
    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"


def test_parse_symbol_uppercased() -> None:
    payload = '[{"symbol": "nvda", "side": "buy"}]'
    signals = parse_message("nvda play", client=_fake_client(payload))
    assert signals[0].symbol == "NVDA"


def test_parse_conviction_normalised() -> None:
    payload = '[{"symbol": "META", "side": "buy", "conviction": "HIGH"}]'
    signals = parse_message("meta buy", client=_fake_client(payload))
    assert signals[0].conviction == "high"
