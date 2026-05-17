"""Tests for LivePortfolioSnapshot using a fake T212 client and in-memory DB."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import Bar, Order, OrderSide, OrderStatus
from ai_agent.loop.portfolio_snapshot import (
    LivePortfolioSnapshot,
    _compute_atr_from_db,
    _trading_days_between,
)

# ---------------------------------------------------------------------------
# Fake T212
# ---------------------------------------------------------------------------


class FakeCash:
    free = Decimal("5_000")
    invested = Decimal("20_000")
    total = Decimal("8_800")  # free + position market value (1800 + 2000)


class FakePosition:
    def __init__(self, ticker: str, quantity: Decimal, current_price: Decimal) -> None:
        self.ticker = ticker
        self.quantity = quantity
        self.current_price = current_price


class FakeT212:
    def get_cash(self) -> FakeCash:
        return FakeCash()

    def get_positions(self) -> list[FakePosition]:
        return [
            FakePosition("AAPL", Decimal("10"), Decimal("180")),
            FakePosition("MSFT", Decimal("5"), Decimal("400")),
        ]


# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _in_memory_db(monkeypatch):
    """Redirect all DB calls to a fresh in-memory SQLite engine for each test."""

    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)

    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)

    # patch get_session to use our engine
    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def _get_session(engine_arg=None) -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(eng_mod, "get_session", _get_session)
    return engine


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_nav_is_t212_account_total() -> None:
    snap = LivePortfolioSnapshot(FakeT212())
    # NAV is T212's reported account total, not a re-derived sum (which would
    # double-count the invested portion).
    assert snap.nav == Decimal("8_800")


def test_position_value_known_ticker() -> None:
    snap = LivePortfolioSnapshot(FakeT212())
    assert snap.position_value("AAPL") == Decimal("1_800")


def test_position_value_unknown_ticker() -> None:
    snap = LivePortfolioSnapshot(FakeT212())
    assert snap.position_value("TSLA") == Decimal("0")


def test_symbol_sector_from_watchlist_map() -> None:
    snap = LivePortfolioSnapshot(FakeT212(), watchlist_sectors={"AAPL": "Technology"})
    assert snap.symbol_sector("AAPL") == "Technology"
    assert snap.symbol_sector("aapl") == "Technology"  # case-insensitive


def test_symbol_sector_unknown() -> None:
    snap = LivePortfolioSnapshot(FakeT212())
    assert snap.symbol_sector("AAPL") is None


def test_sector_value_sums_matching_positions() -> None:
    snap = LivePortfolioSnapshot(
        FakeT212(),
        watchlist_sectors={"AAPL": "Technology", "MSFT": "Technology"},
    )
    # AAPL=1800 + MSFT=2000 = 3800
    assert snap.sector_value("Technology") == Decimal("3_800")


def test_daily_turnover_empty() -> None:
    snap = LivePortfolioSnapshot(FakeT212())
    assert snap.daily_turnover() == Decimal("0")


def test_daily_turnover_counts_submitted_orders(_in_memory_db) -> None:
    today = datetime.now(UTC)
    with Session(_in_memory_db) as session:
        o = Order(
            symbol="AAPL",
            side=OrderSide.buy,
            order_type="limit",
            quantity=Decimal("10"),
            limit_price=Decimal("180"),
            status=OrderStatus.submitted,
            submitted_at=today,
        )
        session.add(o)
        session.commit()

    snap = LivePortfolioSnapshot(FakeT212())
    assert snap.daily_turnover() == Decimal("1_800")


def test_days_since_last_sell_never_sold() -> None:
    snap = LivePortfolioSnapshot(FakeT212())
    assert snap.days_since_last_sell("AAPL") is None


def test_days_since_last_sell_counted(_in_memory_db) -> None:
    ref = date(2026, 5, 5)  # Monday
    sell_date = date(2026, 5, 1)  # previous Thursday → 2 trading days (Thu→Fri→Mon)
    with Session(_in_memory_db) as session:
        o = Order(
            symbol="AAPL",
            side=OrderSide.sell,
            order_type="limit",
            quantity=Decimal("5"),
            limit_price=Decimal("180"),
            status=OrderStatus.filled,
            filled_at=datetime(sell_date.year, sell_date.month, sell_date.day, tzinfo=UTC),
        )
        session.add(o)
        session.commit()

    snap = LivePortfolioSnapshot(FakeT212(), reference_date=ref)
    days = snap.days_since_last_sell("AAPL")
    assert days == 2  # Fri + Mon = 2 trading days


# ---------------------------------------------------------------------------
# _trading_days_between
# ---------------------------------------------------------------------------


def test_trading_days_same_day() -> None:
    d = date(2026, 5, 5)
    assert _trading_days_between(d, d) == 0


def test_trading_days_mon_to_fri() -> None:
    # Mon 2026-05-04 to Fri 2026-05-08 = 4 trading days
    assert _trading_days_between(date(2026, 5, 4), date(2026, 5, 8)) == 4


def test_trading_days_skips_weekend() -> None:
    # Fri 2026-05-08 to Mon 2026-05-11 = 1 trading day (Mon)
    assert _trading_days_between(date(2026, 5, 8), date(2026, 5, 11)) == 1


# ---------------------------------------------------------------------------
# _compute_atr_from_db
# ---------------------------------------------------------------------------


def test_compute_atr_returns_none_no_bars() -> None:
    result = _compute_atr_from_db("AAPL", date(2026, 5, 5))
    assert result is None


def test_compute_atr_basic(_in_memory_db) -> None:
    bars = [
        Bar(
            symbol="AAPL",
            trading_date=date(2026, 1, i + 1),
            open=Decimal("100"),
            high=Decimal(str(100 + i)),
            low=Decimal(str(100 - i)),
            close=Decimal("100"),
            volume=1_000,
            source="test",
        )
        for i in range(15)
    ]
    with Session(_in_memory_db) as session:
        session.add_all(bars)
        session.commit()

    atr = _compute_atr_from_db("AAPL", date(2026, 1, 15))
    assert atr is not None
    assert atr > 0
