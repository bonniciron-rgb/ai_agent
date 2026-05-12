"""Tests for SpyTiltStrategy — the Phase B exposure manager."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import pytest

from ai_agent.backtest.spy_tilt import SpyTiltStrategy
from ai_agent.signals.base import SignalContext, SignalResult


def _make_bars(closes: list[float], start: date | None = None) -> pd.DataFrame:
    start = start or date(2020, 1, 1)
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


def _ts(day: int, start: date = date(2020, 1, 1)) -> pd.Timestamp:
    return pd.Timestamp(start + timedelta(days=day))


def _spy_row(close: float = 400.0) -> pd.Series:
    return pd.Series(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1_000_000}
    )


@dataclass
class _FixedSignal:
    """Always returns a fixed score regardless of context."""

    score: float
    name: str = "fixed"
    version: str = "0.0.0"

    def compute(self, ctx: SignalContext) -> SignalResult:
        return SignalResult(score=self.score)


class TestConstruction:
    def test_invalid_min_alloc_above_max_raises(self):
        with pytest.raises(ValueError, match="min_alloc"):
            SpyTiltStrategy(
                signal=_FixedSignal(1.0),
                universe_bars={"A": _make_bars([100.0] * 60)},
                min_alloc=0.8,
                max_alloc=0.5,
            )

    def test_negative_min_alloc_raises(self):
        with pytest.raises(ValueError, match="min_alloc"):
            SpyTiltStrategy(
                signal=_FixedSignal(1.0),
                universe_bars={"A": _make_bars([100.0] * 60)},
                min_alloc=-0.1,
                max_alloc=1.0,
            )

    def test_negative_rebalance_threshold_raises(self):
        with pytest.raises(ValueError, match="rebalance_threshold"):
            SpyTiltStrategy(
                signal=_FixedSignal(1.0),
                universe_bars={"A": _make_bars([100.0] * 60)},
                rebalance_threshold=-0.01,
            )

    def test_valid_construction(self):
        strat = SpyTiltStrategy(
            signal=_FixedSignal(0.5),
            universe_bars={"A": _make_bars([100.0] * 60)},
        )
        assert strat._min_alloc == 0.5
        assert strat._max_alloc == 1.0


class TestWarmup:
    def test_warmup_returns_zero(self):
        strat = SpyTiltStrategy(
            signal=_FixedSignal(1.0),
            universe_bars={"SPY_PROXY": _make_bars([400.0] * 200)},
            warmup_bars=50,
            rebalance_threshold=0.0,
        )
        strat.reset()
        for i in range(49):
            sig = strat.on_bar(date=_ts(i), row=_spy_row(), position=0, cash=10_000.0)
            assert sig == 0, f"bar {i} should be warmup (got {sig})"


class TestAllocation:
    def _make_strat(self, fixed_score: float, rebalance_threshold: float = 0.0) -> SpyTiltStrategy:
        universe = {"AAPL": _make_bars([100.0] * 200)}
        return SpyTiltStrategy(
            signal=_FixedSignal(fixed_score),
            universe_bars=universe,
            min_alloc=0.5,
            max_alloc=1.0,
            warmup_bars=50,
            rebalance_threshold=rebalance_threshold,
        )

    def test_score_zero_targets_min_alloc(self):
        strat = self._make_strat(0.0)
        strat.reset()
        for i in range(50):
            strat.on_bar(date=_ts(i), row=_spy_row(400.0), position=0, cash=10_000.0)
        # After warmup: target = 50% of 10000 / 400 = 12 shares
        # But position=0, current_alloc=0 → delta = 12 - 0 = 12
        sig = strat.on_bar(date=_ts(50), row=_spy_row(400.0), position=0, cash=10_000.0)
        assert sig == 12  # int(10000 * 0.5 / 400) = 12

    def test_score_one_targets_max_alloc(self):
        strat = self._make_strat(1.0)
        strat.reset()
        for i in range(50):
            strat.on_bar(date=_ts(i), row=_spy_row(400.0), position=0, cash=10_000.0)
        # target = 100% of 10000 / 400 = 25 shares
        sig = strat.on_bar(date=_ts(50), row=_spy_row(400.0), position=0, cash=10_000.0)
        assert sig == 25  # int(10000 * 1.0 / 400) = 25

    def test_score_half_targets_mid_alloc(self):
        strat = self._make_strat(0.5)
        strat.reset()
        for i in range(50):
            strat.on_bar(date=_ts(i), row=_spy_row(400.0), position=0, cash=10_000.0)
        # target = 75% of 10000 / 400 = 18 shares (int(10000*0.75/400)=18)
        sig = strat.on_bar(date=_ts(50), row=_spy_row(400.0), position=0, cash=10_000.0)
        assert sig == 18  # int(10000 * 0.75 / 400) = 18

    def test_rebalance_threshold_suppresses_small_moves(self):
        strat = self._make_strat(1.0, rebalance_threshold=0.1)
        strat.reset()
        for i in range(51):
            strat.on_bar(date=_ts(i), row=_spy_row(400.0), position=0, cash=10_000.0)
        # Fully invested at 25 shares → current_alloc=100%, target=100%, delta=0
        sig = strat.on_bar(date=_ts(51), row=_spy_row(400.0), position=25, cash=0.0)
        assert sig == 0

    def test_reduces_position_when_score_falls(self):
        # Start fully invested, then score=0 targets 50%; should sell
        strat = self._make_strat(0.0, rebalance_threshold=0.0)
        strat.reset()
        # Pre-fill score_by_date with date → 0.0 (FixedSignal always 0)
        for i in range(51):
            strat.on_bar(date=_ts(i), row=_spy_row(400.0), position=0, cash=10_000.0)
        # Simulate: holding 25 shares (100% alloc), target is 50% → should reduce
        sig = strat.on_bar(date=_ts(51), row=_spy_row(400.0), position=25, cash=0.0)
        # NAV = 0 + 25*400 = 10000, target_qty = int(10000*0.5/400) = 12
        # delta = 12 - 25 = -13
        assert sig == -13


class TestEmptyUniverse:
    def test_empty_universe_returns_zero_post_warmup(self):
        strat = SpyTiltStrategy(
            signal=_FixedSignal(1.0),
            universe_bars={},
            warmup_bars=2,
            rebalance_threshold=0.0,
            min_alloc=0.5,
            max_alloc=1.0,
        )
        strat.reset()
        # No universe scores → score defaults to 0.0 → target = min_alloc = 0.5
        # First 2 bars are warmup (bars_seen < warmup_bars)
        strat.on_bar(date=_ts(0), row=_spy_row(), position=0, cash=10_000.0)
        strat.on_bar(date=_ts(1), row=_spy_row(), position=0, cash=10_000.0)
        sig = strat.on_bar(date=_ts(2), row=_spy_row(400.0), position=0, cash=10_000.0)
        # score=0.0, target=50%, int(10000*0.5/400)=12
        assert sig == 12


class TestReset:
    def test_reset_recomputes_score_series(self):
        strat = SpyTiltStrategy(
            signal=_FixedSignal(0.8),
            universe_bars={"X": _make_bars([100.0] * 100)},
            warmup_bars=10,
            rebalance_threshold=0.0,
        )
        strat.reset()
        first_scores = dict(strat._score_by_date)
        strat.reset()
        second_scores = dict(strat._score_by_date)
        assert first_scores == second_scores

    def test_reset_clears_bars_seen(self):
        strat = SpyTiltStrategy(
            signal=_FixedSignal(0.5),
            universe_bars={"X": _make_bars([100.0] * 60)},
            warmup_bars=5,
        )
        strat.reset()
        for i in range(10):
            strat.on_bar(date=_ts(i), row=_spy_row(), position=0, cash=10_000.0)
        strat.reset()
        assert strat._bars_seen == 0
