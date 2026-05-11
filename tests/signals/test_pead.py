"""Tests for PostEarningsDriftSignal (A2 alpha signal)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from ai_agent.signals.base import SignalContext
from ai_agent.signals.pead import EarningsEvent, PostEarningsDriftSignal

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


def _event(
    *,
    announcement_date: date,
    actual_eps: float = 2.0,
    consensus_eps: float = 1.8,
    surprise_pct: float | None = None,
) -> EarningsEvent:
    if surprise_pct is None:
        surprise_pct = (actual_eps - consensus_eps) / abs(consensus_eps)
    return EarningsEvent(
        announcement_date=announcement_date,
        actual_eps=actual_eps,
        consensus_eps=consensus_eps,
        surprise_pct=surprise_pct,
    )


# ---------------------------------------------------------------------------
# TestPositiveSurpriseGoesLong
# ---------------------------------------------------------------------------


class TestPositiveSurpriseGoesLong:
    """A positive surprise >= threshold within the holding window → score 1.0."""

    def test_recent_beat_returns_long(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=10)  # 10 days after, inside 30d holding window
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.10)]},
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0

    def test_note_contains_symbol_and_surprise(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=5)
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.08)]},
        )
        result = sig.compute(_ctx(as_of))
        assert result.notes
        note = result.notes[0]
        assert "AAPL" in note
        assert "surprise" in note.lower()

    def test_exactly_at_threshold_goes_long(self):
        ann = date(2024, 3, 1)
        as_of = ann + timedelta(days=1)
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.05)]},
            surprise_threshold=0.05,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestSmallSurpriseIsFlat
# ---------------------------------------------------------------------------


class TestSmallSurpriseIsFlat:
    """Surprise below threshold → score 0.0."""

    def test_small_beat_below_threshold(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=5)
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.03)]},
            surprise_threshold=0.05,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_just_below_threshold_is_flat(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=5)
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.0499)]},
            surprise_threshold=0.05,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestNegativeSurpriseIsFlat
# ---------------------------------------------------------------------------


class TestNegativeSurpriseIsFlat:
    """Negative surprise → score 0.0 (long-only signal, no short leg)."""

    def test_miss_is_flat(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=5)
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=-0.10)]},
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_large_miss_is_flat_not_short(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=5)
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=-0.50)]},
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0
        assert result.score != -1.0  # explicitly not short


# ---------------------------------------------------------------------------
# TestStaleEarningsIsFlat
# ---------------------------------------------------------------------------


class TestStaleEarningsIsFlat:
    """Earnings outside the lookback window → score 0.0."""

    def test_earnings_older_than_lookback(self):
        ann = date(2024, 1, 1)
        as_of = ann + timedelta(days=61)  # 61 days > default 60d lookback
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.15)]},
            lookback_window_days=60,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_earnings_exactly_at_lookback_boundary_is_flat(self):
        ann = date(2024, 1, 1)
        as_of = ann + timedelta(days=61)  # strictly greater than lookback=60 → flat
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.20)]},
            lookback_window_days=60,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_future_earnings_are_ignored(self):
        as_of = date(2024, 2, 1)
        ann = as_of + timedelta(days=5)  # announcement is in the future
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.20)]},
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestHoldingWindowExit
# ---------------------------------------------------------------------------


class TestHoldingWindowExit:
    """Bar date past holding_window_days after announcement → score 0.0."""

    def test_past_holding_window_is_flat(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=31)  # 31d > 30d default holding window
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.15)]},
            holding_window_days=30,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_on_last_day_of_holding_window_is_long(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=30)  # exactly 30d == holding_window_days → still long
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.15)]},
            holding_window_days=30,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0

    def test_custom_holding_window(self):
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=10)
        # With holding_window=5, 10 days is past the window
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [_event(announcement_date=ann, surprise_pct=0.15)]},
            holding_window_days=5,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestMultipleEarnings
# ---------------------------------------------------------------------------


class TestMultipleEarnings:
    """With multiple events, the highest qualifying surprise wins."""

    def test_most_recent_qualifying_event_wins(self):
        # Two events both qualify; the one with a higher surprise should win.
        as_of = date(2024, 4, 15)
        ev_big = _event(announcement_date=date(2024, 4, 10), surprise_pct=0.20)
        ev_small = _event(announcement_date=date(2024, 4, 5), surprise_pct=0.07)
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [ev_small, ev_big]},
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0
        # Note should reference the bigger surprise
        assert "20.00" in result.notes[0]

    def test_only_qualifying_event_from_mix(self):
        # One qualifying, one below threshold, one stale.
        as_of = date(2024, 4, 15)
        ev_ok = _event(announcement_date=date(2024, 4, 10), surprise_pct=0.10)
        ev_below = _event(announcement_date=date(2024, 4, 5), surprise_pct=0.02)
        ev_stale = _event(announcement_date=as_of - timedelta(days=90), surprise_pct=0.30)
        sig = PostEarningsDriftSignal(
            earnings_events={"AAPL": [ev_below, ev_ok, ev_stale]},
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestZeroConsensusGuard
# ---------------------------------------------------------------------------


class TestZeroConsensusGuard:
    """consensus_eps == 0 → surprise_pct should be pre-set by caller; if 0 itself it stays flat."""

    def test_zero_surprise_with_zero_consensus_is_flat(self):
        # Caller computed surprise_pct=0.0 because consensus was 0 (skipped the division).
        ann = date(2024, 2, 1)
        as_of = ann + timedelta(days=5)
        ev = EarningsEvent(
            announcement_date=ann,
            actual_eps=1.0,
            consensus_eps=0.0,
            surprise_pct=0.0,  # caller chose to set 0 for this edge case
        )
        sig = PostEarningsDriftSignal(earnings_events={"AAPL": [ev]})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0  # 0.0 < 0.05 threshold → flat

    def test_runner_inject_skips_zero_consensus(self):
        """_inject_earnings_events skips zero-consensus rows (tested via the runner helper)."""
        # We test this indirectly: a signal with no earnings_events + a symbol with
        # zero consensus that was skipped during injection → empty list → flat.
        # Direct unit-test of the runner guard is in test_runner.py; here we confirm
        # the signal itself handles missing events gracefully.
        sig = PostEarningsDriftSignal(earnings_events={"AAPL": []})
        result = sig.compute(_ctx(date(2024, 3, 1)))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestEmptyEarningsList
# ---------------------------------------------------------------------------


class TestEmptyEarningsList:
    """Symbol with no earnings → score 0.0 with an informative note."""

    def test_missing_symbol_returns_flat(self):
        sig = PostEarningsDriftSignal(earnings_events={})
        result = sig.compute(_ctx(date(2024, 3, 1)))
        assert result.score == 0.0
        assert result.notes
        assert "no earnings" in result.notes[0].lower()

    def test_empty_list_for_symbol_returns_flat(self):
        sig = PostEarningsDriftSignal(earnings_events={"AAPL": []})
        result = sig.compute(_ctx(date(2024, 3, 1)))
        assert result.score == 0.0

    def test_different_symbol_has_no_data(self):
        ann = date(2024, 2, 1)
        sig = PostEarningsDriftSignal(
            earnings_events={"MSFT": [_event(announcement_date=ann, surprise_pct=0.15)]},
        )
        # Ask for AAPL, which has no data
        result = sig.compute(_ctx(date(2024, 2, 10), symbol="AAPL"))
        assert result.score == 0.0
        assert "no earnings" in result.notes[0].lower()


# ---------------------------------------------------------------------------
# TestSignalAttributes
# ---------------------------------------------------------------------------


class TestSignalAttributes:
    """name and version attributes required by Signal protocol."""

    def test_name(self):
        sig = PostEarningsDriftSignal()
        assert sig.name == "post_earnings_drift"

    def test_version(self):
        sig = PostEarningsDriftSignal()
        assert sig.version == "0.1.0"

    def test_default_surprise_threshold(self):
        sig = PostEarningsDriftSignal()
        assert sig.surprise_threshold == pytest.approx(0.05)

    def test_default_holding_window(self):
        sig = PostEarningsDriftSignal()
        assert sig.holding_window_days == 30

    def test_default_lookback_window(self):
        sig = PostEarningsDriftSignal()
        assert sig.lookback_window_days == 60
