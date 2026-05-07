"""Pipeline that turns a BarSeries into a single FeatureSnapshot row.

This is what the LLM sees as numeric context per ticker, alongside news
and earnings. Computed at the latest bar; for backtests we'd extend with
a windowed variant that yields a snapshot per historical date.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import pandas as pd
from pydantic import BaseModel

from ai_agent.data import BarSeries
from ai_agent.features import indicators as ind
from ai_agent.features.regime import Regime, classify_regime

MIN_BARS = 200


class FeatureSnapshot(BaseModel):
    """Latest-bar feature row for one symbol."""

    symbol: str
    as_of: date
    close: Decimal
    sma_50: Decimal | None = None
    sma_200: Decimal | None = None
    ema_20: Decimal | None = None
    rsi_14: Decimal | None = None
    macd: Decimal | None = None
    macd_signal: Decimal | None = None
    bb_upper: Decimal | None = None
    bb_lower: Decimal | None = None
    atr_14: Decimal | None = None
    adx_14: Decimal | None = None
    volume_ratio_20d: Decimal | None = None
    regime: Regime
    bars_used: int


def _series_to_frame(series: BarSeries) -> pd.DataFrame:
    """Convert a BarSeries to a pandas frame indexed by trading_date."""
    rows = [
        {
            "date": p.trading_date,
            "open": float(p.open),
            "high": float(p.high),
            "low": float(p.low),
            "close": float(p.close),
            "volume": float(p.volume),
        }
        for p in series.points
    ]
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df


def _last(series: pd.Series) -> float | None:
    if len(series) == 0:
        return None
    val = series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


def _to_decimal(v: float | None) -> Decimal | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return Decimal(f"{v:.6f}")


def compute_features(series: BarSeries, *, min_bars: int = MIN_BARS) -> FeatureSnapshot:
    """Compute the latest-bar feature snapshot for a symbol.

    Raises `ValueError` if the series is empty. With fewer than `min_bars`
    points the snapshot is still returned but most fields will be None and
    the regime will be `unknown` — caller decides whether to use it.
    """
    if not series.points:
        raise ValueError(f"BarSeries for {series.symbol!r} is empty")

    df = _series_to_frame(series)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    sma_50 = ind.sma(close, 50)
    sma_200 = ind.sma(close, 200)
    ema_20 = ind.ema(close, 20)
    rsi_14 = ind.rsi(close, 14)
    macd_line, macd_signal_line, _ = ind.macd(close)
    _bb_mid, bb_upper, bb_lower = ind.bollinger_bands(close, 20, 2.0)
    atr_14 = ind.atr(high, low, close, 14)
    adx_14 = ind.adx(high, low, close, 14)
    vol_ratio = ind.volume_vs_avg(volume, 20)

    last_close = _last(close)
    last_sma_200 = _last(sma_200)
    last_adx = _last(adx_14)
    last_bb_upper = _last(bb_upper)
    last_bb_lower = _last(bb_lower)

    regime = classify_regime(
        close=last_close,
        sma_200=last_sma_200,
        adx_14=last_adx,
        bb_upper=last_bb_upper,
        bb_lower=last_bb_lower,
    )

    last_index = df.index[-1]
    as_of = last_index if isinstance(last_index, date) else date.fromisoformat(str(last_index))

    return FeatureSnapshot(
        symbol=series.symbol,
        as_of=as_of,
        close=Decimal(f"{last_close:.6f}") if last_close is not None else Decimal(0),
        sma_50=_to_decimal(_last(sma_50)),
        sma_200=_to_decimal(last_sma_200),
        ema_20=_to_decimal(_last(ema_20)),
        rsi_14=_to_decimal(_last(rsi_14)),
        macd=_to_decimal(_last(macd_line)),
        macd_signal=_to_decimal(_last(macd_signal_line)),
        bb_upper=_to_decimal(last_bb_upper),
        bb_lower=_to_decimal(last_bb_lower),
        atr_14=_to_decimal(_last(atr_14)),
        adx_14=_to_decimal(last_adx),
        volume_ratio_20d=_to_decimal(_last(vol_ratio)),
        regime=regime,
        bars_used=len(df),
    )
