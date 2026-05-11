"""Tests for ShortInterestMomentumSignal (B5 alpha signal)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from ai_agent.signals.base import SignalContext
from ai_agent.signals.short_interest import ShortInterestMomentumSignal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_AS_OF = date(2024, 3, 1)
_DEFAULT_SYMBOL = "GME"


def _make_bars(
    n: int,
    start_price: float = 100.0,
    end_price: float | None = None,
    start: date | None = None,
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame with a linear price ramp from start_price to end_price.

    Parameters
    ----------
    n:
        Number of bars to generate.
    start_price:
        Opening price for the first bar.
    end_price:
        Closing price for the last bar.  If ``None``, all bars close at ``start_price``
        (flat momentum).
    start:
        Date of the first bar.  Defaults to ``_DEFAULT_AS_OF - timedelta(days=n-1)``.
    """
    start = start or (_DEFAULT_AS_OF - timedelta(days=n - 1))
    dates = [start + timedelta(days=i) for i in range(n)]
    if end_price is None:
        closes = [start_price] * n
    else:
        # Linear interpolation from start_price to end_price over n bars.
        step = (end_price - start_price) / max(n - 1, 1)
        closes = [start_price + step * i for i in range(n)]

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


def _ctx(
    as_of: date = _DEFAULT_AS_OF,
    symbol: str = _DEFAULT_SYMBOL,
    *,
    n_bars: int = 25,
    start_price: float = 100.0,
    end_price: float | None = None,
) -> SignalContext:
    """Build a SignalContext with synthetic bars ending on ``as_of``."""
    bars = _make_bars(
        n=n_bars,
        start_price=start_price,
        end_price=end_price,
        start=as_of - timedelta(days=n_bars - 1),
    )
    return SignalContext(symbol=symbol, as_of=as_of, bars=bars)


# ---------------------------------------------------------------------------
# TestSqueezeSetupGoesLong
# ---------------------------------------------------------------------------


class TestSqueezeSetupGoesLong:
    """short_pct >= threshold AND momentum >= threshold → score 1.0."""

    def test_high_short_and_positive_momentum_is_long(self):
        # 25 bars, price rises from 100 to 105 → ~5% 20d return; short_pct 20%
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=105.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.20})
        result = sig.compute(ctx)
        assert result.score == 1.0

    def test_note_contains_symbol(self):
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=110.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.25})
        result = sig.compute(ctx)
        assert result.notes
        assert _DEFAULT_SYMBOL in result.notes[0]

    def test_note_contains_short_pct_and_momentum(self):
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=110.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.30})
        result = sig.compute(ctx)
        assert result.notes
        note = result.notes[0]
        # Should mention short_pct and the return value
        assert "30" in note or "0.30" in note or "30%" in note

    def test_very_high_short_interest_qualifies(self):
        # AMC/GME style: 50% short float + strong rally
        ctx = _ctx(n_bars=25, start_price=10.0, end_price=15.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.50})
        result = sig.compute(ctx)
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestLowShortInterestIsFlat
# ---------------------------------------------------------------------------


class TestLowShortInterestIsFlat:
    """short_pct < threshold → score 0.0 regardless of momentum."""

    def test_low_short_pct_with_strong_momentum_is_flat(self):
        # 30% momentum but only 5% short float — no squeeze fuel
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=130.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.05})
        result = sig.compute(ctx)
        assert result.score == 0.0

    def test_zero_short_pct_is_flat(self):
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=110.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.0})
        result = sig.compute(ctx)
        assert result.score == 0.0

    def test_note_mentions_threshold(self):
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=110.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.05})
        result = sig.compute(ctx)
        assert result.notes
        assert "threshold" in result.notes[0].lower() or "15" in result.notes[0]


# ---------------------------------------------------------------------------
# TestNegativeMomentumIsFlat
# ---------------------------------------------------------------------------


class TestNegativeMomentumIsFlat:
    """High short interest BUT 20d return negative → score 0.0 (avoids falling knife)."""

    def test_high_short_falling_price_is_flat(self):
        # 30% short float but price declining — falling knife, not a squeeze trigger
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=90.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.30})
        result = sig.compute(ctx)
        assert result.score == 0.0

    def test_note_mentions_return_value(self):
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=85.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.30})
        result = sig.compute(ctx)
        assert result.notes
        # Note should indicate the negative momentum
        note = result.notes[0]
        assert "-" in note or "threshold" in note.lower()


# ---------------------------------------------------------------------------
# TestFlatMomentumIsFlat
# ---------------------------------------------------------------------------


class TestFlatMomentumIsFlat:
    """High short interest AND non-negative but below-threshold momentum → score 0.0."""

    def test_zero_momentum_with_high_short_is_flat(self):
        # Flat price — no squeeze trigger
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=100.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.20})
        result = sig.compute(ctx)
        assert result.score == 0.0

    def test_small_positive_momentum_below_threshold_is_flat(self):
        # 1% gain — below the 3% default threshold
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=101.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.20})
        result = sig.compute(ctx)
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestExactThresholdGoesLong
# ---------------------------------------------------------------------------


class TestExactThresholdGoesLong:
    """Conditions use >= not >: exact threshold values should yield score 1.0."""

    def test_exact_short_pct_at_threshold(self):
        # short_pct == min_short_pct exactly → should qualify
        # Use a price that gives momentum well above threshold to isolate short_pct test
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=110.0)
        sig = ShortInterestMomentumSignal(
            short_data={_DEFAULT_SYMBOL: 0.15},
            min_short_pct=0.15,
        )
        result = sig.compute(ctx)
        assert result.score == 1.0

    def test_exact_momentum_at_threshold(self):
        # Craft prices so that 20d return == min_momentum_pct exactly (3.00%)
        # bars[-21] = 100.0, bars[-1] = 103.0 → return = 3%
        n = 25
        closes = [100.0] * n
        closes[-1] = 103.0  # last bar is as_of; base is closes[-(20+1)] = closes[-21] = closes[4]
        as_of = _DEFAULT_AS_OF
        start = as_of - timedelta(days=n - 1)
        dates = [start + timedelta(days=i) for i in range(n)]
        bars = pd.DataFrame(
            {
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": [1_000_000] * n,
            },
            index=pd.Index(dates, name="trading_date"),
        )
        ctx = SignalContext(symbol=_DEFAULT_SYMBOL, as_of=as_of, bars=bars)
        sig = ShortInterestMomentumSignal(
            short_data={_DEFAULT_SYMBOL: 0.20},
            min_momentum_pct=0.03,
        )
        result = sig.compute(ctx)
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestCustomThresholds
# ---------------------------------------------------------------------------


class TestCustomThresholds:
    """Custom min_short_pct, min_momentum_pct, and lookback_days are respected."""

    def test_custom_min_short_pct_lower_threshold(self):
        # With min_short_pct=0.10, a stock with 12% short float should qualify
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=105.0)
        sig = ShortInterestMomentumSignal(
            short_data={_DEFAULT_SYMBOL: 0.12},
            min_short_pct=0.10,
        )
        result = sig.compute(ctx)
        assert result.score == 1.0

    def test_custom_min_short_pct_higher_threshold(self):
        # With min_short_pct=0.25, a stock with 20% short float should NOT qualify
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=115.0)
        sig = ShortInterestMomentumSignal(
            short_data={_DEFAULT_SYMBOL: 0.20},
            min_short_pct=0.25,
        )
        result = sig.compute(ctx)
        assert result.score == 0.0

    def test_custom_min_momentum_pct(self):
        # With min_momentum_pct=0.10 (10%), a 5% gain should NOT qualify
        ctx = _ctx(n_bars=25, start_price=100.0, end_price=105.0)
        sig = ShortInterestMomentumSignal(
            short_data={_DEFAULT_SYMBOL: 0.25},
            min_momentum_pct=0.10,
        )
        result = sig.compute(ctx)
        assert result.score == 0.0

    def test_custom_lookback_days_changes_base_bar(self):
        # With lookback_days=5, we compare bars[-1] vs bars[-6].
        # Build prices: flat at 100, then a sharp jump at the last 5 bars.
        n = 15
        closes = [100.0] * n
        # Last 6 bars: bar[-6]=100, bars[-5...-1] all at 110 → 10% 5d return
        for i in range(n - 5, n):
            closes[i] = 110.0
        # bars[-6] stays at 100
        as_of = _DEFAULT_AS_OF
        start = as_of - timedelta(days=n - 1)
        dates = [start + timedelta(days=i) for i in range(n)]
        bars = pd.DataFrame(
            {
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": [1_000_000] * n,
            },
            index=pd.Index(dates, name="trading_date"),
        )
        ctx = SignalContext(symbol=_DEFAULT_SYMBOL, as_of=as_of, bars=bars)
        sig = ShortInterestMomentumSignal(
            short_data={_DEFAULT_SYMBOL: 0.20},
            lookback_days=5,
            min_momentum_pct=0.05,
        )
        result = sig.compute(ctx)
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestInsufficientHistory
# ---------------------------------------------------------------------------


class TestInsufficientHistory:
    """Fewer than lookback_days + 1 bars → score 0.0 with 'insufficient history' note."""

    def test_too_few_bars_returns_flat(self):
        # Default lookback_days=20; provide only 15 bars
        ctx = _ctx(n_bars=15, start_price=100.0, end_price=110.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.30})
        result = sig.compute(ctx)
        assert result.score == 0.0

    def test_insufficient_history_note(self):
        ctx = _ctx(n_bars=10, start_price=100.0, end_price=115.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.30})
        result = sig.compute(ctx)
        assert result.notes
        assert "insufficient" in result.notes[0].lower() or "history" in result.notes[0].lower()

    def test_exactly_one_bar_short_is_flat(self):
        # Single bar — cannot compute any return
        ctx = _ctx(n_bars=1, start_price=100.0)
        sig = ShortInterestMomentumSignal(short_data={_DEFAULT_SYMBOL: 0.30})
        result = sig.compute(ctx)
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestMissingShortData
# ---------------------------------------------------------------------------


class TestMissingShortData:
    """Symbol not in short_data dict → score 0.0 with informative note."""

    def test_missing_symbol_returns_flat(self):
        ctx = _ctx()
        sig = ShortInterestMomentumSignal(short_data={})
        result = sig.compute(ctx)
        assert result.score == 0.0

    def test_missing_symbol_note_is_informative(self):
        ctx = _ctx()
        sig = ShortInterestMomentumSignal(short_data={})
        result = sig.compute(ctx)
        assert result.notes
        note = result.notes[0].lower()
        assert "no short interest" in note or "short" in note

    def test_wrong_symbol_in_short_data(self):
        # short_data has AAPL but context symbol is GME
        ctx = _ctx(symbol=_DEFAULT_SYMBOL)
        sig = ShortInterestMomentumSignal(short_data={"AAPL": 0.25})
        result = sig.compute(ctx)
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestSignalAttributes
# ---------------------------------------------------------------------------


class TestSignalAttributes:
    """name, version, and default parameter attributes required by Signal protocol."""

    def test_name(self):
        sig = ShortInterestMomentumSignal()
        assert sig.name == "short_interest_momentum"

    def test_version(self):
        sig = ShortInterestMomentumSignal()
        assert sig.version == "0.1.0"

    def test_default_min_short_pct(self):
        sig = ShortInterestMomentumSignal()
        assert sig.min_short_pct == pytest.approx(0.15)

    def test_default_min_momentum_pct(self):
        sig = ShortInterestMomentumSignal()
        assert sig.min_momentum_pct == pytest.approx(0.03)

    def test_default_lookback_days(self):
        sig = ShortInterestMomentumSignal()
        assert sig.lookback_days == 20

    def test_default_short_data_is_empty_dict(self):
        sig = ShortInterestMomentumSignal()
        assert sig.short_data == {}
