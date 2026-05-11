"""Tests for SectorRelativeStrengthSignal (A1 alpha signal)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ai_agent.signals.base import SignalContext
from ai_agent.signals.sector_rs import SectorRelativeStrengthSignal


def _make_bars(closes: list[float], start: date | None = None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame matching the harness format."""
    start = start or date(2022, 1, 3)
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


def _make_etf_series(closes: list[float], start: date | None = None) -> pd.Series:
    """Build an ETF close-price Series with the same date index format."""
    start = start or date(2022, 1, 3)
    dates = [start + timedelta(days=i) for i in range(len(closes))]
    return pd.Series(closes, index=pd.Index(dates, name="trading_date"))


def _ctx(bars: pd.DataFrame, symbol: str = "AAPL") -> SignalContext:
    return SignalContext(symbol=symbol, as_of=bars.index[-1], bars=bars)


class TestOutperformingGoesLong:
    """Stock beats ETF by more than threshold → score 1.0."""

    def test_basic_outperform(self):
        # Stock rises 10%, ETF rises 5% → excess 5% >> 2% threshold
        stock_closes = [100.0] * 20 + [110.0]  # 21 bars, 10% gain over last 20
        etf_closes = [200.0] * 20 + [210.0]  # 5% gain
        bars = _make_bars(stock_closes)
        etf = _make_etf_series(etf_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={"XLK": etf},
        )
        result = sig.compute(_ctx(bars))
        assert result.score == 1.0

    def test_note_contains_excess_and_ticker(self):
        stock_closes = [100.0] * 20 + [110.0]
        etf_closes = [200.0] * 20 + [210.0]
        bars = _make_bars(stock_closes)
        etf = _make_etf_series(etf_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={"XLK": etf},
        )
        result = sig.compute(_ctx(bars))
        assert result.notes
        assert "XLK" in result.notes[0]
        assert "excess" in result.notes[0]


class TestUnderperformingIsFlat:
    """Stock lags ETF → score 0.0."""

    def test_stock_underperforms_etf(self):
        # Stock flat, ETF rises 5% → excess -5% < threshold
        stock_closes = [100.0] * 21
        etf_closes = [200.0] * 20 + [210.0]
        bars = _make_bars(stock_closes)
        etf = _make_etf_series(etf_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={"XLK": etf},
        )
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0

    def test_both_rise_but_stock_less(self):
        # Stock +1%, ETF +5% → excess -4% < threshold
        stock_closes = [100.0] * 20 + [101.0]
        etf_closes = [100.0] * 20 + [105.0]
        bars = _make_bars(stock_closes)
        etf = _make_etf_series(etf_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={"XLK": etf},
        )
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0


class TestThresholdEdge:
    """Excess return exactly at threshold → long; one tick below → flat."""

    def test_exactly_at_threshold_goes_long(self):
        # Stock +7%, ETF +5% → excess exactly 2% == default threshold
        stock_closes = [100.0] * 20 + [107.0]
        etf_closes = [100.0] * 20 + [105.0]
        bars = _make_bars(stock_closes)
        etf = _make_etf_series(etf_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={"XLK": etf},
        )
        result = sig.compute(_ctx(bars))
        assert result.score == 1.0

    def test_just_below_threshold_stays_flat(self):
        # Stock +6.99%, ETF +5% → excess 1.99% < 2% threshold
        stock_closes = [100.0] * 20 + [106.99]
        etf_closes = [100.0] * 20 + [105.0]
        bars = _make_bars(stock_closes)
        etf = _make_etf_series(etf_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={"XLK": etf},
        )
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0

    def test_custom_threshold(self):
        # With threshold=0.0, any positive excess → long
        stock_closes = [100.0] * 20 + [101.0]
        etf_closes = [100.0] * 20 + [100.5]
        bars = _make_bars(stock_closes)
        etf = _make_etf_series(etf_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={"XLK": etf},
            threshold=0.0,
        )
        result = sig.compute(_ctx(bars))
        assert result.score == 1.0


class TestMissingSectorMapFallsBackToSpy:
    """Symbol not in sector_map should use SPY (default_etf)."""

    def test_missing_symbol_uses_spy(self):
        stock_closes = [100.0] * 20 + [110.0]
        spy_closes = [400.0] * 20 + [404.0]  # SPY +1% → stock excess = +9%
        bars = _make_bars(stock_closes)
        spy = _make_etf_series(spy_closes)
        # No sector_map entry for AAPL; sector_prices has SPY
        sig = SectorRelativeStrengthSignal(
            sector_map={},
            sector_prices={"SPY": spy},
        )
        result = sig.compute(_ctx(bars, symbol="AAPL"))
        assert result.score == 1.0

    def test_missing_symbol_note_references_spy(self):
        stock_closes = [100.0] * 20 + [110.0]
        spy_closes = [400.0] * 20 + [404.0]
        bars = _make_bars(stock_closes)
        spy = _make_etf_series(spy_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={},
            sector_prices={"SPY": spy},
        )
        result = sig.compute(_ctx(bars, symbol="AAPL"))
        assert result.notes
        assert "SPY" in result.notes[0]


class TestInsufficientHistory:
    """Fewer bars than lookback + 1 → flat with informative note."""

    def test_fewer_bars_than_lookback_returns_flat(self):
        sig = SectorRelativeStrengthSignal(lookback=20)
        bars = _make_bars([100.0] * 20)  # exactly 20 bars; need 21
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0
        assert "insufficient history" in result.notes[0]

    def test_one_bar_short_is_flat(self):
        sig = SectorRelativeStrengthSignal(lookback=20)
        bars = _make_bars([100.0] * 20)
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0

    def test_no_etf_prices_returns_flat(self):
        stock_closes = [100.0] * 21
        bars = _make_bars(stock_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={},  # XLK not in sector_prices
        )
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0
        assert "no sector prices" in result.notes[0]

    def test_exactly_lookback_plus_one_bars_computes(self):
        # 21 bars is the minimum required for lookback=20
        stock_closes = [100.0] * 20 + [115.0]  # +15%
        etf_closes = [100.0] * 20 + [105.0]  # +5%
        bars = _make_bars(stock_closes)
        etf = _make_etf_series(etf_closes)
        sig = SectorRelativeStrengthSignal(
            sector_map={"AAPL": "XLK"},
            sector_prices={"XLK": etf},
        )
        result = sig.compute(_ctx(bars))
        assert result.score == 1.0


class TestSignalAttributes:
    """name and version attributes required by Signal protocol."""

    def test_name(self):
        sig = SectorRelativeStrengthSignal()
        assert sig.name == "sector_relative_strength"

    def test_version(self):
        sig = SectorRelativeStrengthSignal()
        assert sig.version == "v1"

    def test_default_etf_is_spy(self):
        sig = SectorRelativeStrengthSignal()
        assert sig.default_etf == "SPY"
