"""Tests for external_signals store using in-memory SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.external_signals.models import ParsedSignal, RawMessage
from ai_agent.external_signals.store import (
    get_latest_posted_at,
    get_signals_for_symbol,
    mark_processed,
    message_exists,
    save_message,
    save_signal,
)

# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)

    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)

    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def _get_session(engine_arg=None) -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(eng_mod, "get_session", _get_session)
    return engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHANNEL = "@JdubTrades_Telegram"
# Relative to the real clock: get_signals_for_symbol filters by
# datetime.now(UTC) - days_back, so a hardcoded date silently breaks the
# days_back assertions once wall-clock time drifts past the window.
NOW = datetime.now(UTC)


def _msg(message_id: int = 1, offset_hours: int = 0) -> RawMessage:
    return RawMessage(
        message_id=message_id,
        channel=CHANNEL,
        posted_at=NOW - timedelta(hours=offset_hours),
        text=f"Signal #{message_id}",
    )


def _signal(symbol: str = "AAPL") -> ParsedSignal:
    return ParsedSignal(
        symbol=symbol,
        side="buy",
        entry_price=Decimal("150"),
        stop_price=Decimal("145"),
        conviction="medium",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_save_and_check_message_exists() -> None:
    msg = _msg(message_id=10)
    assert not message_exists(CHANNEL, 10)
    save_message(msg)
    assert message_exists(CHANNEL, 10)


def test_save_message_returns_id() -> None:
    db_id = save_message(_msg(message_id=20))
    assert isinstance(db_id, int)
    assert db_id > 0


def test_message_exists_different_channel() -> None:
    save_message(_msg(message_id=5))
    assert not message_exists("@OtherChannel", 5)


def test_get_latest_posted_at_empty() -> None:
    assert get_latest_posted_at(CHANNEL) is None


def test_get_latest_posted_at_returns_most_recent() -> None:
    save_message(_msg(message_id=1, offset_hours=5))
    save_message(_msg(message_id=2, offset_hours=2))
    save_message(_msg(message_id=3, offset_hours=10))
    latest = get_latest_posted_at(CHANNEL)
    assert latest is not None
    # Most recent = offset_hours=2 → NOW - 2h
    # SQLite strips tzinfo on retrieval, compare as naive
    expected = (NOW - timedelta(hours=2)).replace(tzinfo=None)
    assert latest.replace(tzinfo=None) == expected


def test_mark_processed() -> None:
    from ai_agent.db.models import ExternalMessage

    db_id = save_message(_msg(message_id=99))
    mark_processed(db_id)

    import ai_agent.db.engine as eng_mod

    with eng_mod.get_session() as session:
        row = session.get(ExternalMessage, db_id)
        assert row is not None
        assert row.processed is True


def test_save_and_get_signal() -> None:
    db_id = save_message(_msg(message_id=50))
    sig = _signal("AAPL")
    save_signal(sig, db_id, CHANNEL, NOW)

    results = get_signals_for_symbol("AAPL", days_back=30)
    assert len(results) == 1
    r = results[0]
    assert r.symbol == "AAPL"
    assert r.side == "buy"
    assert r.entry_price == Decimal("150")
    assert r.conviction == "medium"


def test_get_signals_case_insensitive() -> None:
    db_id = save_message(_msg(message_id=51))
    save_signal(_signal("AAPL"), db_id, CHANNEL, NOW)
    assert len(get_signals_for_symbol("aapl", days_back=30)) == 1


def test_get_signals_respects_days_back() -> None:
    old_posted = NOW - timedelta(days=10)
    db_id = save_message(
        RawMessage(message_id=60, channel=CHANNEL, posted_at=old_posted, text="old")
    )
    save_signal(_signal("AAPL"), db_id, CHANNEL, old_posted)

    # days_back=5 → signal from 10 days ago should NOT appear
    assert get_signals_for_symbol("AAPL", days_back=5) == []
    # days_back=30 → should appear
    assert len(get_signals_for_symbol("AAPL", days_back=30)) == 1


def test_get_signals_filters_by_symbol() -> None:
    db_id_a = save_message(_msg(message_id=70))
    db_id_b = save_message(_msg(message_id=71))
    save_signal(_signal("AAPL"), db_id_a, CHANNEL, NOW)
    save_signal(_signal("MSFT"), db_id_b, CHANNEL, NOW)

    aapl_sigs = get_signals_for_symbol("AAPL", days_back=30)
    msft_sigs = get_signals_for_symbol("MSFT", days_back=30)
    assert len(aapl_sigs) == 1
    assert len(msft_sigs) == 1
    assert aapl_sigs[0].symbol == "AAPL"
    assert msft_sigs[0].symbol == "MSFT"
