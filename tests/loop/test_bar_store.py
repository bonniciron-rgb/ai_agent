"""Tests for bar ingestion + read-back from the DB."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session

from ai_agent.data.base import BarPoint, BarSeries, SymbolNotFoundError
from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.loop.bar_store import bars_from_db, ingest_bars


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
# Fake source
# ---------------------------------------------------------------------------


def _make_series(symbol: str, num: int = 5) -> BarSeries:
    end = date(2026, 5, 5)
    points = [
        BarPoint(
            symbol=symbol,
            trading_date=end - timedelta(days=num - 1 - i),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("102"),
            volume=1_000_000,
            source="fake",
        )
        for i in range(num)
    ]
    return BarSeries(symbol=symbol, points=points)


class FakeSource:
    name = "fake"

    def __init__(self, series_by_symbol: dict[str, BarSeries]) -> None:
        self._map = series_by_symbol

    def get_daily(self, symbol, start, end):
        if symbol not in self._map:
            raise SymbolNotFoundError(symbol)
        return self._map[symbol]


# ---------------------------------------------------------------------------
# ingest_bars
# ---------------------------------------------------------------------------


def test_ingest_inserts_new_bars() -> None:
    src = FakeSource({"AAPL": _make_series("AAPL", num=3)})
    inserted = ingest_bars(["AAPL"], source=src, today=date(2026, 5, 5))
    assert inserted == 3


def test_ingest_is_idempotent() -> None:
    src = FakeSource({"AAPL": _make_series("AAPL", num=3)})
    ingest_bars(["AAPL"], source=src, today=date(2026, 5, 5))
    inserted_again = ingest_bars(["AAPL"], source=src, today=date(2026, 5, 5))
    assert inserted_again == 0


def test_ingest_skips_missing_symbol() -> None:
    src = FakeSource({"AAPL": _make_series("AAPL", num=3)})
    inserted = ingest_bars(["AAPL", "MSFT"], source=src, today=date(2026, 5, 5))
    assert inserted == 3  # MSFT raises SymbolNotFoundError, only AAPL succeeds


def test_ingest_handles_source_exception() -> None:
    class BadSource:
        name = "bad"

        def get_daily(self, *args, **kwargs):
            raise RuntimeError("network down")

    inserted = ingest_bars(["AAPL"], source=BadSource(), today=date(2026, 5, 5))
    assert inserted == 0


def test_ingest_multiple_symbols() -> None:
    src = FakeSource(
        {
            "AAPL": _make_series("AAPL", num=3),
            "MSFT": _make_series("MSFT", num=2),
        }
    )
    inserted = ingest_bars(["AAPL", "MSFT"], source=src, today=date(2026, 5, 5))
    assert inserted == 5


# ---------------------------------------------------------------------------
# bars_from_db
# ---------------------------------------------------------------------------


def test_bars_from_db_empty_when_no_bars() -> None:
    series = bars_from_db("AAPL", days_back=30, ref_date=date(2026, 5, 5))
    assert len(series.points) == 0


def test_bars_from_db_returns_in_date_order() -> None:
    src = FakeSource({"AAPL": _make_series("AAPL", num=5)})
    ingest_bars(["AAPL"], source=src, today=date(2026, 5, 5))

    series = bars_from_db("AAPL", days_back=30, ref_date=date(2026, 5, 5))
    assert len(series.points) == 5
    dates = [p.trading_date for p in series.points]
    assert dates == sorted(dates)


def test_bars_from_db_respects_days_back() -> None:
    src = FakeSource({"AAPL": _make_series("AAPL", num=10)})
    ingest_bars(["AAPL"], source=src, today=date(2026, 5, 5))

    # Only the last 3 bars
    series = bars_from_db("AAPL", days_back=3, ref_date=date(2026, 5, 5))
    assert len(series.points) <= 4  # 0..3 days back inclusive


def test_bars_from_db_filters_by_symbol() -> None:
    src = FakeSource(
        {
            "AAPL": _make_series("AAPL", num=3),
            "MSFT": _make_series("MSFT", num=3),
        }
    )
    ingest_bars(["AAPL", "MSFT"], source=src, today=date(2026, 5, 5))

    aapl = bars_from_db("AAPL", days_back=30, ref_date=date(2026, 5, 5))
    msft = bars_from_db("MSFT", days_back=30, ref_date=date(2026, 5, 5))
    assert len(aapl.points) == 3
    assert len(msft.points) == 3
    assert all(p.symbol == "AAPL" for p in aapl.points)
    assert all(p.symbol == "MSFT" for p in msft.points)


def test_bars_from_db_case_insensitive() -> None:
    src = FakeSource({"AAPL": _make_series("AAPL", num=3)})
    ingest_bars(["AAPL"], source=src, today=date(2026, 5, 5))

    assert len(bars_from_db("aapl", ref_date=date(2026, 5, 5)).points) == 3
