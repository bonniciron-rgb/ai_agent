"""Technical indicators in vanilla pandas/numpy.

These are the deterministic numerical inputs to the LLM proposal step.
Implemented in-house (no pandas-ta dependency) to keep CI fast and the
behaviour fully under our control.

All functions take a `pd.Series` of close prices (or OHLC frames where
noted) and return a `pd.Series` of the same length, with NaN for the
warm-up window.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(close: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return close.rolling(window=window, min_periods=window).mean()


def ema(close: pd.Series, window: int) -> pd.Series:
    """Exponential moving average (pandas adjusted=False = Wilders/EMA)."""
    return close.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative strength index, Wilder's smoothing."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()

    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0.0, 100.0)
    return out


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    close: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (mid, upper, lower) Bollinger Bands."""
    mid = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid, upper, lower


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range = max(H-L, |H-C_prev|, |L-C_prev|)."""
    prev_close = close.shift(1)
    tr_a = high - low
    tr_b = (high - prev_close).abs()
    tr_c = (low - prev_close).abs()
    return pd.concat([tr_a, tr_b, tr_c], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range, Wilder's smoothing."""
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average Directional Index. >25 = strong trend, <20 = ranging."""
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = true_range(high, low, close)
    atr_w = tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()

    plus_di = 100.0 * (
        plus_dm.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
        / atr_w.replace(0.0, np.nan)
    )
    minus_di = 100.0 * (
        minus_dm.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
        / atr_w.replace(0.0, np.nan)
    )

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def volume_vs_avg(volume: pd.Series, window: int = 20) -> pd.Series:
    """Ratio of current volume to its trailing N-day average."""
    avg = volume.rolling(window=window, min_periods=window).mean()
    return volume / avg.replace(0.0, np.nan)
