"""Tests for reference signals — AlwaysFlatSignal and SmaCrossSignal."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ai_agent.signals.base import SignalContext
from ai_agent.signals.reference import AlwaysFlatSignal, SmaCrossSignal


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


class TestAlwaysFlatSignal:
    def test_returns_zero_score(self):
        sig = AlwaysFlatSignal()
        bars = _make_bars([100.0] * 50)
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0

    def test_returns_zero_confidence(self):
        sig = AlwaysFlatSignal()
        bars = _make_bars([100.0] * 50)
        result = sig.compute(_ctx(bars))
        assert result.confidence == 0.0

    def test_score_zero_regardless_of_uptrend(self):
        sig = AlwaysFlatSignal()
        closes = [float(i) for i in range(1, 300)]
        bars = _make_bars(closes)
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0

    def test_score_zero_regardless_of_downtrend(self):
        sig = AlwaysFlatSignal()
        closes = [float(300 - i) for i in range(300)]
        bars = _make_bars(closes)
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0


class TestSmaCrossSignal:
    def test_insufficient_data_returns_zero(self):
        sig = SmaCrossSignal(fast=50, slow=200)
        bars = _make_bars([100.0] * 199)  # one bar short of slow window
        result = sig.compute(_ctx(bars))
        assert result.score == 0.0
        assert "insufficient data" in result.notes[0]

    def test_uptrending_returns_positive_score(self):
        sig = SmaCrossSignal(fast=50, slow=200)
        # Strongly uptrending: 200+ bars of rising prices
        closes = [100.0 + i * 0.5 for i in range(210)]
        bars = _make_bars(closes)
        result = sig.compute(_ctx(bars))
        assert result.score > 0.0

    def test_downtrending_returns_negative_score(self):
        sig = SmaCrossSignal(fast=50, slow=200)
        # Strongly downtrending: 200+ bars of falling prices
        closes = [300.0 - i * 0.5 for i in range(210)]
        bars = _make_bars(closes)
        result = sig.compute(_ctx(bars))
        assert result.score < 0.0

    def test_score_capped_at_one(self):
        sig = SmaCrossSignal(fast=50, slow=200)
        # Extremely steep uptrend to force score > 1 before capping
        closes = [100.0 + i * 5.0 for i in range(210)]
        bars = _make_bars(closes)
        result = sig.compute(_ctx(bars))
        assert result.score <= 1.0

    def test_exactly_slow_bars_triggers_computation(self):
        sig = SmaCrossSignal(fast=50, slow=200)
        closes = [100.0 + i * 0.5 for i in range(200)]
        bars = _make_bars(closes)
        # 200 bars == slow window; should compute (not return insufficient)
        result = sig.compute(_ctx(bars))
        assert "insufficient data" not in (result.notes[0] if result.notes else "")
