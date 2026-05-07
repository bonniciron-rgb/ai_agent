from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from ai_agent.data import BarPoint, BarSeries
from ai_agent.features import FeatureSnapshot, Regime, compute_features


def _trend_series(symbol: str = "AAPL", n: int = 250, start_price: float = 100.0) -> BarSeries:
    closes = np.linspace(start_price, start_price * 3.5, n)
    points = []
    base = date(2024, 1, 1)
    for i, c in enumerate(closes):
        points.append(
            BarPoint(
                symbol=symbol,
                trading_date=base + timedelta(days=i),
                open=Decimal(f"{c - 0.5:.4f}"),
                high=Decimal(f"{c + 1.0:.4f}"),
                low=Decimal(f"{c - 1.0:.4f}"),
                close=Decimal(f"{c:.4f}"),
                volume=1_000_000,
                source="test",
            )
        )
    return BarSeries(symbol=symbol, points=points)


def _short_series(n: int) -> BarSeries:
    closes = np.linspace(100, 110, n)
    points = []
    base = date(2024, 1, 1)
    for i, c in enumerate(closes):
        points.append(
            BarPoint(
                symbol="MSFT",
                trading_date=base + timedelta(days=i),
                open=Decimal(f"{c:.4f}"),
                high=Decimal(f"{c + 0.5:.4f}"),
                low=Decimal(f"{c - 0.5:.4f}"),
                close=Decimal(f"{c:.4f}"),
                volume=500_000,
                source="test",
            )
        )
    return BarSeries(symbol="MSFT", points=points)


def test_empty_series_rejected() -> None:
    with pytest.raises(ValueError):
        compute_features(BarSeries(symbol="AAPL"))


def test_full_window_produces_complete_snapshot() -> None:
    snap = compute_features(_trend_series())
    assert isinstance(snap, FeatureSnapshot)
    assert snap.symbol == "AAPL"
    assert snap.bars_used == 250
    assert snap.close > 0
    assert snap.sma_50 is not None
    assert snap.sma_200 is not None
    assert snap.ema_20 is not None
    assert snap.rsi_14 is not None
    assert snap.macd is not None
    assert snap.bb_upper is not None
    assert snap.atr_14 is not None
    assert snap.adx_14 is not None


def test_clean_uptrend_classified_as_trending_up() -> None:
    snap = compute_features(_trend_series())
    assert snap.regime is Regime.trending_up
    assert snap.adx_14 is not None and snap.adx_14 >= Decimal("25")
    # rising series above its own 200dma
    assert snap.sma_200 is not None
    assert snap.close > snap.sma_200


def test_short_series_yields_unknown_regime() -> None:
    snap = compute_features(_short_series(50))
    assert snap.bars_used == 50
    assert snap.sma_50 is not None  # 50-day SMA reaches the last bar with exactly 50 bars
    assert snap.sma_200 is None  # not enough data for 200-day SMA
    assert snap.regime is Regime.unknown


def test_as_of_uses_latest_bar_date() -> None:
    snap = compute_features(_trend_series(n=100))
    assert snap.as_of == date(2024, 1, 1) + timedelta(days=99)


def test_atr_within_expected_range_for_trend() -> None:
    snap = compute_features(_trend_series())
    # ATR should reflect ~2.0 daily range plus small step; loosely 2-10
    assert snap.atr_14 is not None
    assert Decimal("0.5") <= snap.atr_14 <= Decimal("20")
