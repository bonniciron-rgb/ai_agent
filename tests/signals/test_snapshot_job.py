"""Tests for the daily quant-signal snapshot job (Batch 54)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import Bar, SignalSnapshot
from ai_agent.signals import snapshot_job
from ai_agent.signals.base import SignalResult

AS_OF = date(2026, 5, 20)


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)
    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)

    @contextmanager
    def _get_session(engine_arg=None) -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(eng_mod, "get_session", _get_session)
    return engine


def _seed_bars(engine, symbol: str = "AAPL", n: int = 80) -> None:
    with Session(engine) as s:
        d = AS_OF - timedelta(days=1)
        price = 100.0
        added = 0
        while added < n:
            if d.weekday() < 5:  # weekday
                s.add(
                    Bar(
                        symbol=symbol,
                        trading_date=d,
                        open=Decimal(str(price)),
                        high=Decimal(str(price + 1)),
                        low=Decimal(str(price - 1)),
                        close=Decimal(str(price)),
                        volume=1_000_000,
                        source="test",
                    )
                )
                price += 0.5
                added += 1
            d -= timedelta(days=1)
        s.commit()


def _go_offline(monkeypatch) -> None:
    """Neutralise every live-data injection so compute_snapshots stays offline."""
    for name in (
        "_inject_earnings_events",
        "_inject_recommendations",
        "_inject_insider_events",
        "_inject_short_interest",
    ):
        monkeypatch.setattr(snapshot_job, name, lambda *a, **k: None)


def test_compute_snapshots_structure(_db, monkeypatch) -> None:
    _go_offline(monkeypatch)
    _seed_bars(_db, "AAPL")

    results = snapshot_job.compute_snapshots(["AAPL"], as_of=AS_OF)

    assert set(results) == {"AAPL"}
    assert set(results["AAPL"]) == {
        "post_earnings_drift",
        "analyst_revision_momentum",
        "insider_buying",
        "short_interest_momentum",
    }
    # No live data injected → every signal neutral.
    assert all(r.score == 0.0 for r in results["AAPL"].values())


def test_compute_skips_symbol_with_too_few_bars(_db, monkeypatch) -> None:
    _go_offline(monkeypatch)
    _seed_bars(_db, "AAPL", n=10)  # below WARMUP_BARS

    assert snapshot_job.compute_snapshots(["AAPL"], as_of=AS_OF) == {}


def test_persist_and_latest_roundtrip(_db) -> None:
    results = {
        "AAPL": {
            "post_earnings_drift": SignalResult(score=1.0, confidence=1.0, notes=["beat +5%"]),
            "insider_buying": SignalResult(score=0.0, confidence=1.0),
        }
    }
    assert snapshot_job.persist_snapshots(results, as_of=AS_OF) == 1

    snap = snapshot_job.latest_snapshot("aapl")  # case-insensitive lookup
    assert snap is not None
    assert snap.symbol == "AAPL"
    assert snap.active_count == 1
    assert abs(snap.composite_score - 0.5) < 1e-9
    payload = json.loads(snap.signals_json)
    assert payload["post_earnings_drift"]["notes"] == ["beat +5%"]


def test_persist_upserts_on_same_day(_db) -> None:
    snapshot_job.persist_snapshots(
        {"AAPL": {"insider_buying": SignalResult(score=0.0)}}, as_of=AS_OF
    )
    snapshot_job.persist_snapshots(
        {"AAPL": {"insider_buying": SignalResult(score=1.0)}}, as_of=AS_OF
    )

    with Session(_db) as s:
        rows = list(s.exec(select(SignalSnapshot).where(SignalSnapshot.symbol == "AAPL")).all())
    assert len(rows) == 1  # upserted, not duplicated
    assert rows[0].composite_score == 1.0


def test_latest_snapshot_missing_returns_none(_db) -> None:
    assert snapshot_job.latest_snapshot("ZZZZ") is None
