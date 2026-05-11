"""Tests for AnalystRevisionMomentumSignal (B2 alpha signal)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from ai_agent.signals.analyst_revisions import (
    AnalystRevisionMomentumSignal,
    RecommendationSnapshot,
)
from ai_agent.signals.base import SignalContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(n: int = 30, start: date | None = None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame; prices are flat (signal ignores them)."""
    start = start or date(2024, 1, 2)
    dates = [start + timedelta(days=i) for i in range(n)]
    closes = [100.0] * n
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * n,
        },
        index=pd.Index(dates, name="trading_date"),
    )


def _ctx(as_of: date, symbol: str = "AAPL") -> SignalContext:
    bars = _make_bars(start=as_of - timedelta(days=29))
    return SignalContext(symbol=symbol, as_of=as_of, bars=bars)


def _snap(
    period: date,
    *,
    strong_buy: int = 0,
    buy: int = 0,
    hold: int = 0,
    sell: int = 0,
    strong_sell: int = 0,
) -> RecommendationSnapshot:
    return RecommendationSnapshot(
        period=period,
        strong_buy=strong_buy,
        buy=buy,
        hold=hold,
        sell=sell,
        strong_sell=strong_sell,
    )


def _month(base: date, offset: int) -> date:
    """Return a date *offset* months after (or before, if negative) *base*."""
    import calendar

    m = base.month + offset
    y = base.year
    while m > 12:
        m -= 12
        y += 1
    while m <= 0:
        m += 12
        y -= 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(base.day, last_day))


# ---------------------------------------------------------------------------
# TestImprovingStreakGoesLong
# ---------------------------------------------------------------------------


class TestImprovingStreakGoesLong:
    """3 consecutive months of improving bullish_score → score 1.0."""

    def test_three_month_streak_returns_long(self):
        as_of = date(2024, 4, 30)
        snaps = [
            # Improving: -0.5, 0.0, 0.5 (strictly increasing over 3 months)
            _snap(_month(as_of, -3), sell=10, strong_sell=5, hold=5),  # negative
            _snap(_month(as_of, -2), hold=20),  # 0.0
            _snap(_month(as_of, -1), buy=10, hold=10),  # 0.5
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0

    def test_note_contains_symbol_and_streak_length(self):
        as_of = date(2024, 4, 30)
        snaps = [
            _snap(_month(as_of, -3), hold=10),
            _snap(_month(as_of, -2), buy=5, hold=5),
            _snap(_month(as_of, -1), buy=10, hold=5),
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.notes
        note = result.notes[0]
        assert "AAPL" in note
        assert "streak" in note.lower()

    def test_longer_streak_also_qualifies(self):
        as_of = date(2024, 6, 30)
        # 5 consecutive months of strictly increasing bullish_score
        snaps = [
            _snap(_month(as_of, -5), sell=10, hold=10),
            _snap(_month(as_of, -4), hold=20),
            _snap(_month(as_of, -3), buy=5, hold=15),
            _snap(_month(as_of, -2), buy=10, hold=10),
            _snap(_month(as_of, -1), buy=15, hold=5),
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestShortStreakIsFlat
# ---------------------------------------------------------------------------


class TestShortStreakIsFlat:
    """Only 2 consecutive improvements → score 0.0 when threshold is 3."""

    def test_two_months_below_default_threshold(self):
        as_of = date(2024, 4, 30)
        # Scores in order: 0.25, 0.5, 0.25 (third drops → only trailing streak of 1 at end)
        # Working backwards from last: 0.25 vs 0.5 → 0.25 < 0.5 → streak breaks immediately.
        # So streak = 1, which is < min_consecutive_months=3 → flat.
        snaps = [
            _snap(_month(as_of, -3), buy=5, hold=15),  # 0.25
            _snap(_month(as_of, -2), buy=10, hold=10),  # 0.5 — up
            _snap(_month(as_of, -1), buy=5, hold=15),  # 0.25 — down (breaks streak)
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_note_indicates_short_streak(self):
        as_of = date(2024, 4, 30)
        snaps = [
            _snap(_month(as_of, -4), buy=10, hold=10),
            _snap(_month(as_of, -3), hold=20),
            _snap(_month(as_of, -2), buy=5, hold=15),
            _snap(_month(as_of, -1), buy=10, hold=10),
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.notes
        assert "2" in result.notes[0] or "streak" in result.notes[0].lower()


# ---------------------------------------------------------------------------
# TestPlateauIsFlat
# ---------------------------------------------------------------------------


class TestPlateauIsFlat:
    """Bullish score flat (not strictly increasing) → score 0.0."""

    def test_identical_scores_not_a_streak(self):
        as_of = date(2024, 4, 30)
        # All snapshots have the same bullish_score (hold-only = 0.0)
        snaps = [
            _snap(_month(as_of, -3), hold=10),
            _snap(_month(as_of, -2), hold=10),
            _snap(_month(as_of, -1), hold=10),
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_plateau_after_rise_breaks_streak(self):
        as_of = date(2024, 4, 30)
        snaps = [
            _snap(_month(as_of, -3), hold=20),  # 0.0
            _snap(_month(as_of, -2), buy=10, hold=10),  # 0.5
            _snap(_month(as_of, -1), buy=10, hold=10),  # 0.5 (plateau, not strictly increasing)
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestDeterioratingIsFlat
# ---------------------------------------------------------------------------


class TestDeterioratingIsFlat:
    """Bullish score decreasing → score 0.0."""

    def test_declining_scores_is_flat(self):
        as_of = date(2024, 4, 30)
        snaps = [
            _snap(_month(as_of, -3), buy=15, hold=5),  # 0.75
            _snap(_month(as_of, -2), buy=10, hold=10),  # 0.5
            _snap(_month(as_of, -1), hold=20),  # 0.0
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_mixed_up_down_up_breaks_streak(self):
        as_of = date(2024, 4, 30)
        snaps = [
            _snap(_month(as_of, -3), hold=20),  # 0.0
            _snap(_month(as_of, -2), buy=10, hold=10),  # 0.5
            _snap(_month(as_of, -1), hold=20),  # 0.0 (down — breaks streak)
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestStaleStreakIsFlat
# ---------------------------------------------------------------------------


class TestStaleStreakIsFlat:
    """Streak ended more than lookback_months ago → score 0.0."""

    def test_streak_outside_lookback_window(self):
        as_of = date(2024, 6, 30)
        # Streak of 3 months, but all older than lookback_months=3 from as_of
        snaps = [
            _snap(date(2023, 11, 30), hold=20),  # ~7 months before as_of
            _snap(date(2023, 12, 31), buy=5, hold=15),  # ~6 months before
            _snap(date(2024, 1, 31), buy=10, hold=10),  # ~5 months before
            # nothing in [Apr-Jun 2024] -> all 3 improving snaps fall outside 3mo window
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
            lookback_months=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestCustomThresholds
# ---------------------------------------------------------------------------


class TestCustomThresholds:
    """min_consecutive_months=5 and custom lookback_months work as configured."""

    def test_five_month_threshold_requires_five(self):
        as_of = date(2024, 7, 31)
        # 4 improving months — not enough for threshold=5
        snaps = [
            _snap(_month(as_of, -5), sell=10, hold=10),
            _snap(_month(as_of, -4), hold=20),
            _snap(_month(as_of, -3), buy=5, hold=15),
            _snap(_month(as_of, -2), buy=10, hold=10),
            _snap(_month(as_of, -1), buy=15, hold=5),
        ]
        # Only last 4 are improving (first drop at -5 → -4 breaks it)
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=5,
            lookback_months=6,
        )
        result = sig.compute(_ctx(as_of))
        # Scores: -5 < -4 < -3 < -2 < -1 — actually 5 months all improving
        # Let's verify: sell=10,hold=10 → (0-10-0)/20 = -0.5
        # hold=20 → 0.0, buy=5,hold=15 → 5/20=0.25, buy=10,hold=10 → 10/20=0.5, buy=15,hold=5 → 15/20=0.75
        # That's 5 consecutive improvements — score should be 1.0
        assert result.score == 1.0

    def test_five_month_threshold_fails_with_four_improving(self):
        as_of = date(2024, 7, 31)
        snaps = [
            _snap(_month(as_of, -5), buy=15, hold=5),  # 0.75 (higher than next → breaks streak)
            _snap(_month(as_of, -4), hold=20),  # 0.0 — drops
            _snap(_month(as_of, -3), buy=5, hold=15),  # 0.25
            _snap(_month(as_of, -2), buy=10, hold=10),  # 0.5
            _snap(_month(as_of, -1), buy=15, hold=5),  # 0.75
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=5,
            lookback_months=6,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0  # only 4 consecutive at end

    def test_custom_lookback_restricts_window(self):
        as_of = date(2024, 6, 30)
        # 3 improving months, all within 2 months → not in lookback_months=2 fully
        snaps = [
            _snap(_month(as_of, -3), hold=20),  # outside 2mo window
            _snap(_month(as_of, -2), buy=5, hold=15),
            _snap(_month(as_of, -1), buy=10, hold=10),
        ]
        sig = AnalystRevisionMomentumSignal(
            recommendations={"AAPL": snaps},
            min_consecutive_months=3,
            lookback_months=2,
        )
        result = sig.compute(_ctx(as_of))
        # Only 2 snaps inside 2mo window; need 3 → flat
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestEmptyRecommendations
# ---------------------------------------------------------------------------


class TestEmptyRecommendations:
    """No data → score 0.0 with an informative note."""

    def test_missing_symbol_returns_flat(self):
        sig = AnalystRevisionMomentumSignal(recommendations={})
        result = sig.compute(_ctx(date(2024, 4, 30)))
        assert result.score == 0.0
        assert result.notes
        assert "no recommendation" in result.notes[0].lower()

    def test_empty_list_for_symbol_returns_flat(self):
        sig = AnalystRevisionMomentumSignal(recommendations={"AAPL": []})
        result = sig.compute(_ctx(date(2024, 4, 30)))
        assert result.score == 0.0

    def test_different_symbol_has_no_data(self):
        as_of = date(2024, 4, 30)
        snaps = [
            _snap(_month(as_of, -3), hold=10),
            _snap(_month(as_of, -2), buy=5, hold=5),
            _snap(_month(as_of, -1), buy=10, hold=5),
        ]
        sig = AnalystRevisionMomentumSignal(recommendations={"MSFT": snaps})
        result = sig.compute(_ctx(as_of, symbol="AAPL"))
        assert result.score == 0.0
        assert "no recommendation" in result.notes[0].lower()


# ---------------------------------------------------------------------------
# TestBullishScoreCalculation
# ---------------------------------------------------------------------------


class TestBullishScoreCalculation:
    """Direct unit tests of the bullish_score property on RecommendationSnapshot."""

    def test_all_strong_buy_gives_positive_two(self):
        snap = _snap(date(2024, 1, 31), strong_buy=10)
        assert snap.bullish_score == pytest.approx(2.0)

    def test_all_strong_sell_gives_negative_two(self):
        snap = _snap(date(2024, 1, 31), strong_sell=5)
        assert snap.bullish_score == pytest.approx(-2.0)

    def test_all_hold_gives_zero(self):
        snap = _snap(date(2024, 1, 31), hold=20)
        assert snap.bullish_score == pytest.approx(0.0)

    def test_mixed_formula(self):
        # (2*2 + 3*1 - 1*1 - 0*2) / (2+3+4+1+0) = (4+3-1)/10 = 6/10 = 0.6
        snap = _snap(date(2024, 1, 31), strong_buy=2, buy=3, hold=4, sell=1, strong_sell=0)
        assert snap.bullish_score == pytest.approx(0.6)

    def test_no_analysts_gives_zero(self):
        snap = _snap(date(2024, 1, 31))  # all zeros
        assert snap.bullish_score == pytest.approx(0.0)

    def test_buy_and_sell_balance_to_zero(self):
        # (0*2 + 5*1 - 5*1 - 0*2) / (0+5+0+5+0) = 0/10 = 0.0
        snap = _snap(date(2024, 1, 31), buy=5, sell=5)
        assert snap.bullish_score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestSignalAttributes
# ---------------------------------------------------------------------------


class TestSignalAttributes:
    """name, version, and dataclass attributes required by Signal protocol."""

    def test_name(self):
        sig = AnalystRevisionMomentumSignal()
        assert sig.name == "analyst_revision_momentum"

    def test_version(self):
        sig = AnalystRevisionMomentumSignal()
        assert sig.version == "0.1.0"

    def test_default_min_consecutive_months(self):
        sig = AnalystRevisionMomentumSignal()
        assert sig.min_consecutive_months == 3

    def test_default_lookback_months(self):
        sig = AnalystRevisionMomentumSignal()
        assert sig.lookback_months == 6

    def test_default_recommendations_is_empty_dict(self):
        sig = AnalystRevisionMomentumSignal()
        assert sig.recommendations == {}

    def test_snapshot_dataclass_fields(self):
        snap = RecommendationSnapshot(
            period=date(2024, 1, 31),
            strong_buy=5,
            buy=3,
            hold=2,
            sell=1,
            strong_sell=0,
        )
        assert snap.period == date(2024, 1, 31)
        assert snap.strong_buy == 5
        assert snap.buy == 3
        assert snap.hold == 2
        assert snap.sell == 1
        assert snap.strong_sell == 0
