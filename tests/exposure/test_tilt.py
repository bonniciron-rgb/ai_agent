"""Tests for the exposure-manager tilt engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import pytest

from ai_agent.exposure.tilt import (
    TiltSnapshot,
    compute_tilt_snapshot,
    score_to_allocation,
    tilt_summary_line,
)
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


@dataclass
class _FixedSignal:
    score: float
    name: str = "fixed"
    version: str = "0.0.0"

    def compute(self, ctx: SignalContext) -> SignalResult:
        return SignalResult(score=self.score)


@dataclass
class _PerSymbolSignal:
    """Returns a different score depending on the symbol."""

    scores: dict
    name: str = "per_symbol"
    version: str = "0.0.0"

    def compute(self, ctx: SignalContext) -> SignalResult:
        return SignalResult(score=self.scores.get(ctx.symbol, 0.0))


# --- score_to_allocation ---------------------------------------------------


class TestScoreToAllocation:
    def test_default_band_passthrough(self):
        assert score_to_allocation(0.0) == pytest.approx(0.5)
        assert score_to_allocation(0.5) == pytest.approx(0.75)
        assert score_to_allocation(1.0) == pytest.approx(1.0)

    def test_ceiling_compresses(self):
        assert score_to_allocation(0.0, score_ceiling=0.3) == pytest.approx(0.5)
        assert score_to_allocation(0.15, score_ceiling=0.3) == pytest.approx(0.75)
        assert score_to_allocation(0.3, score_ceiling=0.3) == pytest.approx(1.0)

    def test_clamps_above_and_below(self):
        assert score_to_allocation(5.0, score_ceiling=0.3) == pytest.approx(1.0)
        assert score_to_allocation(-1.0) == pytest.approx(0.5)

    def test_margin_band(self):
        # live config: 50-150%
        assert score_to_allocation(1.0, max_alloc=1.5) == pytest.approx(1.5)
        assert score_to_allocation(0.5, max_alloc=1.5) == pytest.approx(1.0)

    def test_degenerate_band_raises(self):
        with pytest.raises(ValueError, match="score_floor"):
            score_to_allocation(0.1, score_floor=0.3, score_ceiling=0.3)

    def test_invalid_alloc_raises(self):
        with pytest.raises(ValueError, match="min_alloc"):
            score_to_allocation(0.5, min_alloc=0.8, max_alloc=0.5)


# --- compute_tilt_snapshot -------------------------------------------------


class TestComputeTiltSnapshot:
    def test_all_bullish(self):
        universe = {"A": _make_bars([100.0] * 60), "B": _make_bars([100.0] * 60)}
        snap = compute_tilt_snapshot(_FixedSignal(1.0), universe, score_ceiling=1.0)
        assert snap.composite_score == pytest.approx(1.0)
        assert snap.target_allocation == pytest.approx(1.0)
        assert snap.n_symbols == 2
        assert snap.allocation_pct == 100

    def test_all_flat_falls_to_min_alloc(self):
        universe = {"A": _make_bars([100.0] * 60)}
        snap = compute_tilt_snapshot(_FixedSignal(0.0), universe)
        assert snap.composite_score == 0.0
        assert snap.target_allocation == pytest.approx(0.5)

    def test_partial_breadth(self):
        # 1 of 4 bullish → composite 0.25 → with ceiling 0.3 → alloc ≈ 0.917
        universe = {s: _make_bars([100.0] * 60) for s in ("A", "B", "C", "D")}
        sig = _PerSymbolSignal({"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0})
        snap = compute_tilt_snapshot(sig, universe, score_ceiling=0.3)
        assert snap.composite_score == pytest.approx(0.25)
        assert snap.target_allocation == pytest.approx(0.5 + (0.25 / 0.3) * 0.5)
        assert snap.per_symbol_scores == {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0}

    def test_skips_short_history(self):
        universe = {
            "A": _make_bars([100.0] * 60),
            "SHORT": _make_bars([100.0] * 10),  # < warmup_bars
        }
        snap = compute_tilt_snapshot(_FixedSignal(1.0), universe, warmup_bars=50)
        assert snap.n_symbols == 1
        assert "SHORT" not in snap.per_symbol_scores

    def test_empty_universe_defaults_defensive(self):
        snap = compute_tilt_snapshot(_FixedSignal(1.0), {})
        assert snap.n_symbols == 0
        assert snap.composite_score == 0.0
        assert snap.target_allocation == pytest.approx(0.5)

    def test_as_of_is_latest_bar_date(self):
        start = date(2021, 6, 1)
        universe = {"A": _make_bars([100.0] * 60, start=start)}
        snap = compute_tilt_snapshot(_FixedSignal(0.5), universe)
        assert snap.as_of == start + timedelta(days=59)

    def test_explicit_as_of_override(self):
        universe = {"A": _make_bars([100.0] * 60)}
        forced = date(2099, 1, 1)
        snap = compute_tilt_snapshot(_FixedSignal(0.5), universe, as_of=forced)
        assert snap.as_of == forced

    def test_signal_exception_skips_symbol(self):
        @dataclass
        class _Boom:
            name: str = "boom"
            version: str = "0.0.0"

            def compute(self, ctx: SignalContext) -> SignalResult:
                raise RuntimeError("kaboom")

        universe = {"A": _make_bars([100.0] * 60)}
        snap = compute_tilt_snapshot(_Boom(), universe)
        assert snap.n_symbols == 0


# --- tilt_summary_line -----------------------------------------------------


class TestTiltSummaryLine:
    def _snap(self, alloc: float, score: float, n: int = 11) -> TiltSnapshot:
        return TiltSnapshot(
            as_of=date(2026, 5, 12),
            composite_score=score,
            target_allocation=alloc,
            n_symbols=n,
        )

    def test_basic_line(self):
        line = tilt_summary_line(self._snap(0.65, 0.09))
        assert "65% SPY" in line
        assert "+0.09" in line
        assert "11 names" in line

    def test_up_from_yesterday(self):
        line = tilt_summary_line(self._snap(0.65, 0.09), prev_allocation=0.60)
        assert "up 5pp" in line

    def test_down_from_yesterday(self):
        line = tilt_summary_line(self._snap(0.55, 0.05), prev_allocation=0.70)
        assert "down 15pp" in line

    def test_unchanged(self):
        line = tilt_summary_line(self._snap(0.65, 0.09), prev_allocation=0.65)
        assert "unchanged" in line

    def test_no_prev_no_delta(self):
        line = tilt_summary_line(self._snap(0.65, 0.09))
        assert "yesterday" not in line


def test_allocation_pct_rounds():
    snap = TiltSnapshot(
        as_of=date(2026, 5, 12), composite_score=0.1, target_allocation=0.6666, n_symbols=5
    )
    assert snap.allocation_pct == 67
