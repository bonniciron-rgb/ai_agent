"""Sanity checks for indicators against hand-computed expectations.

These tests verify behaviour, not exact bit-equivalence with TA-Lib.
"""

import numpy as np
import pandas as pd
import pytest

from ai_agent.features import indicators as ind


@pytest.fixture
def trend_close() -> pd.Series:
    # 250 bars rising from 100 to 350 linearly
    return pd.Series(np.linspace(100, 350, 250))


@pytest.fixture
def flat_close() -> pd.Series:
    return pd.Series([100.0] * 250)


@pytest.fixture
def ohlc_trend() -> tuple[pd.Series, pd.Series, pd.Series]:
    closes = pd.Series(np.linspace(100, 350, 250))
    highs = closes + 1.0
    lows = closes - 1.0
    return highs, lows, closes


def test_sma_warmup_then_average(flat_close: pd.Series) -> None:
    s = ind.sma(flat_close, 50)
    assert s.iloc[:49].isna().all()
    assert pytest.approx(100.0) == s.iloc[49]
    assert pytest.approx(100.0) == s.iloc[-1]


def test_ema_converges_for_constant_series(flat_close: pd.Series) -> None:
    e = ind.ema(flat_close, 20)
    assert pytest.approx(100.0) == e.iloc[-1]


def test_rsi_for_pure_uptrend_is_high(trend_close: pd.Series) -> None:
    r = ind.rsi(trend_close, 14)
    assert r.iloc[-1] >= 95.0  # all gains, no losses → near 100


def test_rsi_for_flat_series_is_undefined_or_neutral(flat_close: pd.Series) -> None:
    # No movement: avg_gain == avg_loss == 0; division-by-zero is masked to 100
    # by convention used here. Just assert it's finite or 100.
    r = ind.rsi(flat_close, 14)
    last = r.iloc[-1]
    assert last == 100.0 or last == 0.0


def test_macd_lengths_and_consistency(trend_close: pd.Series) -> None:
    line, signal, hist = ind.macd(trend_close)
    assert len(line) == len(signal) == len(hist) == len(trend_close)
    diff = (line - signal).dropna()
    valid_hist = hist.dropna()
    assert np.allclose(valid_hist.to_numpy(), diff.loc[valid_hist.index].to_numpy(), atol=1e-9)


def test_bollinger_bands_envelope(trend_close: pd.Series) -> None:
    mid, upper, lower = ind.bollinger_bands(trend_close, 20, 2.0)
    # Upper >= mid >= lower wherever defined
    valid = mid.notna()
    assert (upper[valid] >= mid[valid] - 1e-9).all()
    assert (mid[valid] >= lower[valid] - 1e-9).all()


def test_atr_positive_for_volatile_series(
    ohlc_trend: tuple[pd.Series, pd.Series, pd.Series],
) -> None:
    high, low, close = ohlc_trend
    a = ind.atr(high, low, close, 14)
    last = a.iloc[-1]
    assert last > 0.0
    # Range is high-low + |jump in close|; with linear close, TR ≈ 2 + step.
    # Step = 250/249 ≈ 1.0, so ATR ≈ 3.
    assert 2.0 <= last <= 4.0


def test_adx_strong_for_clean_trend(
    ohlc_trend: tuple[pd.Series, pd.Series, pd.Series],
) -> None:
    high, low, close = ohlc_trend
    a = ind.adx(high, low, close, 14)
    assert a.iloc[-1] >= 50.0  # very strong directional movement


def test_volume_ratio_for_constant_volume() -> None:
    v = pd.Series([1000.0] * 100)
    r = ind.volume_vs_avg(v, 20)
    assert pytest.approx(1.0) == r.iloc[-1]


def test_volume_ratio_for_spike() -> None:
    v = pd.Series([1000.0] * 99 + [5000.0])
    r = ind.volume_vs_avg(v, 20)
    assert r.iloc[-1] > 4.0  # 5x baseline drives the ratio above 4
