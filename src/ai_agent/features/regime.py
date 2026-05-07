"""Per-ticker regime classification.

Four regimes:
- trending_up   : close > SMA200 AND ADX >= 25
- trending_down : close < SMA200 AND ADX >= 25
- ranging       : ADX < 20 (regardless of trend direction)
- breakout      : ADX 20-25 with close pushing above/below Bollinger band
- unknown       : not enough data (warm-up period)

Different LLM prompt strategies apply per regime — e.g. don't propose
mean-reversion entries in a trending market, don't propose breakouts in
a ranging market.
"""

from __future__ import annotations

import math
from enum import StrEnum


class Regime(StrEnum):
    trending_up = "trending_up"
    trending_down = "trending_down"
    ranging = "ranging"
    breakout = "breakout"
    unknown = "unknown"


def classify_regime(
    *,
    close: float | None,
    sma_200: float | None,
    adx_14: float | None,
    bb_upper: float | None,
    bb_lower: float | None,
    adx_strong: float = 25.0,
    adx_weak: float = 20.0,
) -> Regime:
    """Classify the current bar's regime from a few indicator scalars.

    Designed to be called with the most recent row of a feature frame.
    Any None / NaN input means we're still in warm-up → `unknown`.
    """
    if close is None or sma_200 is None or adx_14 is None:
        return Regime.unknown
    if any(math.isnan(x) for x in (close, sma_200, adx_14)):
        return Regime.unknown

    if adx_14 >= adx_strong:
        return Regime.trending_up if close > sma_200 else Regime.trending_down

    if adx_14 < adx_weak:
        return Regime.ranging

    if (
        bb_upper is not None
        and bb_lower is not None
        and not math.isnan(bb_upper)
        and (close > bb_upper or close < bb_lower)
    ):
        return Regime.breakout

    return Regime.ranging
