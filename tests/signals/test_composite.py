"""Tests for CompositeFactorSignal — the v3 multi-factor blend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import pytest

from ai_agent.signals.base import SignalContext, SignalResult
from ai_agent.signals.composite import CompositeFactorSignal


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
        index=pd.Index(dates, name="trading_date"),
    )


def _ctx(bars: pd.DataFrame, symbol: str = "TEST") -> SignalContext:
    return SignalContext(symbol=symbol, as_of=bars.index[-1], bars=bars)


@dataclass
class StubSignal:
    """Test double that returns a fixed score on every compute()."""

    fixed_score: float
    name: str = "stub"
    version: str = "0.0.0"

    def compute(self, ctx: SignalContext) -> SignalResult:
        return SignalResult(score=self.fixed_score, notes=[f"{self.name}={self.fixed_score}"])


class TestConstruction:
    def test_empty_sub_signals_raises(self):
        with pytest.raises(ValueError, match="at least one sub-signal"):
            CompositeFactorSignal(sub_signals=[])

    def test_weights_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="must equal len"):
            CompositeFactorSignal(
                sub_signals=[StubSignal(1.0), StubSignal(1.0)],
                weights=[1.0, 2.0, 3.0],
            )

    def test_zero_weight_sum_raises(self):
        with pytest.raises(ValueError, match="Sum of weights must be positive"):
            CompositeFactorSignal(
                sub_signals=[StubSignal(1.0), StubSignal(1.0)],
                weights=[0.0, 0.0],
            )

    def test_negative_weight_sum_raises(self):
        with pytest.raises(ValueError, match="Sum of weights must be positive"):
            CompositeFactorSignal(
                sub_signals=[StubSignal(1.0)],
                weights=[-1.0],
            )

    def test_default_equal_weights(self):
        sig = CompositeFactorSignal(sub_signals=[StubSignal(1.0)] * 3)
        assert sig.weights == [1.0, 1.0, 1.0]

    def test_custom_weights_preserved(self):
        sig = CompositeFactorSignal(
            sub_signals=[StubSignal(1.0)] * 3,
            weights=[2.0, 3.0, 5.0],
        )
        assert sig.weights == [2.0, 3.0, 5.0]

    def test_name_suffix_applied(self):
        sig = CompositeFactorSignal(
            sub_signals=[StubSignal(1.0)],
            name_suffix="balanced",
        )
        assert sig.name == "composite_factor_balanced"

    def test_default_name_no_suffix(self):
        sig = CompositeFactorSignal(sub_signals=[StubSignal(1.0)])
        assert sig.name == "composite_factor"


class TestComputeEqualWeights:
    def test_all_bullish_returns_one(self):
        sig = CompositeFactorSignal(
            sub_signals=[
                StubSignal(1.0, name="a1"),
                StubSignal(1.0, name="a2"),
                StubSignal(1.0, name="b2"),
            ]
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert result.score == pytest.approx(1.0)

    def test_all_flat_returns_zero(self):
        sig = CompositeFactorSignal(
            sub_signals=[StubSignal(0.0) for _ in range(3)],
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert result.score == 0.0

    def test_one_of_three_returns_one_third(self):
        sig = CompositeFactorSignal(
            sub_signals=[
                StubSignal(1.0, name="a1"),
                StubSignal(0.0, name="a2"),
                StubSignal(0.0, name="b2"),
            ]
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert result.score == pytest.approx(1.0 / 3)

    def test_two_of_three_returns_two_thirds(self):
        sig = CompositeFactorSignal(
            sub_signals=[
                StubSignal(1.0, name="a1"),
                StubSignal(1.0, name="a2"),
                StubSignal(0.0, name="b2"),
            ]
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert result.score == pytest.approx(2.0 / 3)


class TestComputeWeighted:
    def test_double_weight_dominates(self):
        # b2 gets weight 2; a1 and a2 each weight 1.
        # If b2=1.0 and others=0.0, score = (0 + 0 + 2) / 4 = 0.5
        sig = CompositeFactorSignal(
            sub_signals=[
                StubSignal(0.0, name="a1"),
                StubSignal(0.0, name="a2"),
                StubSignal(1.0, name="b2"),
            ],
            weights=[1.0, 1.0, 2.0],
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert result.score == pytest.approx(0.5)

    def test_weights_normalised_internally(self):
        # Weights 10, 10, 10 should give the same result as 1, 1, 1.
        sig_a = CompositeFactorSignal(
            sub_signals=[StubSignal(1.0), StubSignal(0.0), StubSignal(0.5)],
            weights=[1.0, 1.0, 1.0],
        )
        sig_b = CompositeFactorSignal(
            sub_signals=[StubSignal(1.0), StubSignal(0.0), StubSignal(0.5)],
            weights=[10.0, 10.0, 10.0],
        )
        ctx = _ctx(_make_bars([100.0] * 10))
        assert sig_a.compute(ctx).score == pytest.approx(sig_b.compute(ctx).score)

    def test_single_signal_passthrough(self):
        sig = CompositeFactorSignal(sub_signals=[StubSignal(0.7)])
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert result.score == pytest.approx(0.7)


class TestContinuousScoring:
    def test_continuous_sub_signal_scores(self):
        # Sub-signals returning continuous values (not just 0/1)
        sig = CompositeFactorSignal(
            sub_signals=[StubSignal(0.3), StubSignal(0.5), StubSignal(0.7)],
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert result.score == pytest.approx(0.5)  # (0.3 + 0.5 + 0.7) / 3

    def test_score_bounded_when_subsignals_bounded(self):
        # If all sub-signals are in [0, 1], composite is also in [0, 1]
        sig = CompositeFactorSignal(
            sub_signals=[StubSignal(0.99), StubSignal(0.99), StubSignal(0.99)],
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert 0.0 <= result.score <= 1.0


class TestNotes:
    def test_notes_include_composite_score(self):
        sig = CompositeFactorSignal(
            sub_signals=[
                StubSignal(1.0, name="a1"),
                StubSignal(0.0, name="a2"),
            ]
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        assert "composite=" in result.notes[0]

    def test_notes_include_all_sub_signal_names(self):
        sig = CompositeFactorSignal(
            sub_signals=[
                StubSignal(1.0, name="sector_rs"),
                StubSignal(0.0, name="pead"),
                StubSignal(1.0, name="analyst_rev"),
            ]
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        note = result.notes[0]
        assert "sector_rs" in note
        assert "pead" in note
        assert "analyst_rev" in note

    def test_notes_include_sub_signal_scores(self):
        sig = CompositeFactorSignal(
            sub_signals=[
                StubSignal(0.42, name="a1"),
                StubSignal(0.83, name="a2"),
            ]
        )
        result = sig.compute(_ctx(_make_bars([100.0] * 10)))
        note = result.notes[0]
        assert "0.42" in note
        assert "0.83" in note


class TestAttributes:
    def test_has_name_attribute(self):
        sig = CompositeFactorSignal(sub_signals=[StubSignal(0.0)])
        assert sig.name == "composite_factor"

    def test_has_version_attribute(self):
        sig = CompositeFactorSignal(sub_signals=[StubSignal(0.0)])
        assert sig.version == "0.1.0"

    def test_sub_signals_preserved(self):
        a, b = StubSignal(0.0, name="a"), StubSignal(0.0, name="b")
        sig = CompositeFactorSignal(sub_signals=[a, b])
        assert sig.sub_signals == [a, b]
