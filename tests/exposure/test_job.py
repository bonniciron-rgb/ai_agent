"""Tests for the production exposure-manager job."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from ai_agent.exposure.job import (
    MIN_ALLOC,
    SCORE_CEILING,
    SECTOR_MAP,
    UNIVERSE,
    build_composite_signal,
    latest_snapshot,
    make_snapshot,
    persist_snapshot,
)
from ai_agent.exposure.tilt import TiltSnapshot


def _bars(closes: list[float], start: date = date(2022, 1, 1)) -> pd.DataFrame:
    dates = [start + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates]),
    )


def _flat_etf_series(n: int = 120, start: date = date(2022, 1, 1)) -> pd.Series:
    dates = [start + timedelta(days=i) for i in range(n)]
    return pd.Series([400.0] * n, index=dates)


class TestUniverseConstants:
    def test_universe_is_11_symbols(self):
        assert len(UNIVERSE) == 11
        assert set(UNIVERSE) == set(SECTOR_MAP.keys())

    def test_no_defensive_or_pharma(self):
        for dropped in ("JNJ", "PFE", "UNH", "KO", "PEP", "PG"):
            assert dropped not in SECTOR_MAP


class TestBuildComposite:
    def test_three_sub_signals(self):
        sig = build_composite_signal({})
        assert len(sig.sub_signals) == 3
        assert sig.name == "composite_factor_equal_weight"

    def test_works_without_finnhub_data(self):
        # No earnings/recs → A2 and B2 just return 0.0; should not raise.
        sig = build_composite_signal({"SPY": _flat_etf_series()})
        assert sig is not None


class TestMakeSnapshot:
    def test_flat_market_defensive(self):
        # All prices flat → A1 never beats sector → composite 0 → min_alloc.
        universe_bars = {s: _bars([100.0] * 120) for s in UNIVERSE}
        sector_prices = {etf: _flat_etf_series() for etf in {*SECTOR_MAP.values(), "SPY"}}
        snap = make_snapshot(universe_bars, sector_prices)
        assert isinstance(snap, TiltSnapshot)
        assert snap.n_symbols == 11
        assert snap.composite_score == 0.0
        assert snap.target_allocation == MIN_ALLOC
        assert snap.score_ceiling == SCORE_CEILING

    def test_skips_symbols_with_short_history(self):
        universe_bars = {s: _bars([100.0] * 120) for s in UNIVERSE}
        universe_bars["AAPL"] = _bars([100.0] * 10)  # too short
        sector_prices = {etf: _flat_etf_series() for etf in {*SECTOR_MAP.values(), "SPY"}}
        snap = make_snapshot(universe_bars, sector_prices)
        assert snap.n_symbols == 10
        assert "AAPL" not in snap.per_symbol_scores


class TestPersistence:
    def test_roundtrip(self, in_memory_engine):
        snap = TiltSnapshot(
            as_of=date(2026, 5, 12),
            composite_score=0.12,
            target_allocation=0.7,
            n_symbols=11,
            per_symbol_scores={"AAPL": 1.0, "MSFT": 0.0},
            score_ceiling=0.3,
        )
        row = persist_snapshot(snap, engine=in_memory_engine)
        assert row.id is not None
        assert row.allocation_pct == 70

        latest = latest_snapshot(engine=in_memory_engine)
        assert latest is not None
        assert latest.as_of == date(2026, 5, 12)
        assert latest.composite_score == 0.12
        assert json.loads(latest.per_symbol_scores_json) == {"AAPL": 1.0, "MSFT": 0.0}

    def test_upsert_same_date(self, in_memory_engine):
        d = date(2026, 5, 12)
        persist_snapshot(
            TiltSnapshot(as_of=d, composite_score=0.1, target_allocation=0.6, n_symbols=11),
            engine=in_memory_engine,
        )
        persist_snapshot(
            TiltSnapshot(as_of=d, composite_score=0.2, target_allocation=0.7, n_symbols=11),
            engine=in_memory_engine,
        )
        latest = latest_snapshot(engine=in_memory_engine)
        assert latest is not None
        assert latest.composite_score == 0.2
        assert latest.target_allocation == 0.7

    def test_latest_picks_most_recent(self, in_memory_engine):
        persist_snapshot(
            TiltSnapshot(
                as_of=date(2026, 5, 10), composite_score=0.1, target_allocation=0.6, n_symbols=11
            ),
            engine=in_memory_engine,
        )
        persist_snapshot(
            TiltSnapshot(
                as_of=date(2026, 5, 12), composite_score=0.3, target_allocation=0.8, n_symbols=11
            ),
            engine=in_memory_engine,
        )
        latest = latest_snapshot(engine=in_memory_engine)
        assert latest is not None
        assert latest.as_of == date(2026, 5, 12)

    def test_latest_none_when_empty(self, in_memory_engine):
        assert latest_snapshot(engine=in_memory_engine) is None
