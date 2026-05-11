"""B5: Short Interest + Momentum Divergence Signal — fifth real alpha signal through C1 harness.

Goes long when a stock has BOTH high short interest (squeeze fuel) AND positive recent
price momentum (squeeze trigger).  Avoids the "falling knife" trap of high-short-interest
stocks that continue to decline.

Academic basis: Substantial short interest creates a mechanical demand overhang — if the
stock rallies, short sellers must buy to cover, amplifying the move.  The momentum filter
selects stocks where the squeeze has already begun (price is turning up), rather than
simply buying any heavily-shorted name.  See Asquith, Pathak & Ritter (2005) and the
broader short-squeeze literature.

Entry condition (BOTH required):
  1. ``short_percent_of_float >= min_short_pct``  (default: 0.15 = 15%)
  2. 20-day trailing return >= ``min_momentum_pct`` (default: 0.03 = 3%)

Score: 1.0 if both conditions met, 0.0 otherwise.

Long-only.  No short leg on low-short-interest stocks (reserved for a future variant).

Data note:
  ``short_data`` is populated by the runner via ``yf.Ticker(symbol).info["shortPercentOfFloat"]``.
  NYSE/NASDAQ publish updated short interest ~twice per month; the latest snapshot value
  is sufficient for this signal.  Tests inject ``short_data`` directly — no yfinance calls
  in the test suite.
"""

from __future__ import annotations

import pandas as pd

from ai_agent.signals.base import SignalContext, SignalResult

_DEFAULT_MIN_SHORT_PCT = 0.15
_DEFAULT_MIN_MOMENTUM_PCT = 0.03
_DEFAULT_LOOKBACK_DAYS = 20


class ShortInterestMomentumSignal:
    """Long when short interest is elevated AND recent price momentum is positive.

    Parameters
    ----------
    short_data:
        Pre-fetched short interest snapshot keyed by symbol.  Each value is the most
        recent ``shortPercentOfFloat`` expressed as a decimal (e.g., 0.18 for 18%).
        The runner / test setup is responsible for populating this dict; the signal
        performs no I/O.
    min_short_pct:
        Minimum ``shortPercentOfFloat`` (as a decimal) required to qualify.  Default 0.15.
    min_momentum_pct:
        Minimum 20-day trailing return required to qualify.  Default 0.03 (3%).
    lookback_days:
        Number of calendar bars used to compute the trailing return.  The return is
        computed as ``(close[-1] / close[-lookback_days - 1]) - 1`` using the ``bars``
        close series from ``SignalContext``.  Default 20.
    """

    name = "short_interest_momentum"
    version = "0.1.0"

    def __init__(
        self,
        short_data: dict[str, float] | None = None,
        min_short_pct: float = _DEFAULT_MIN_SHORT_PCT,
        min_momentum_pct: float = _DEFAULT_MIN_MOMENTUM_PCT,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self.short_data: dict[str, float] = short_data or {}
        self.min_short_pct = min_short_pct
        self.min_momentum_pct = min_momentum_pct
        self.lookback_days = lookback_days

    def compute(self, ctx: SignalContext) -> SignalResult:
        """Return ``score=1.0`` when squeeze-setup conditions are met, ``0.0`` otherwise."""
        # ------------------------------------------------------------------
        # Condition 1: short interest threshold
        # ------------------------------------------------------------------
        short_pct = self.short_data.get(ctx.symbol)
        if short_pct is None:
            return SignalResult(
                score=0.0,
                notes=[f"no short interest data for {ctx.symbol} (short_pct defaulting to 0.0)"],
            )

        if short_pct < self.min_short_pct:
            return SignalResult(
                score=0.0,
                notes=[
                    f"{ctx.symbol} short_percent_of_float {short_pct:.1%} "
                    f"< threshold {self.min_short_pct:.1%} — insufficient squeeze fuel"
                ],
            )

        # ------------------------------------------------------------------
        # Condition 2: price momentum over the lookback window
        # ------------------------------------------------------------------
        closes: pd.Series = ctx.bars["close"]

        # Need at least lookback_days + 1 bars (one extra for the base price).
        if len(closes) < self.lookback_days + 1:
            return SignalResult(
                score=0.0,
                notes=[
                    f"{ctx.symbol} insufficient history: {len(closes)} bar(s) available, "
                    f"need {self.lookback_days + 1} to compute {self.lookback_days}d return"
                ],
            )

        close_now = float(closes.iloc[-1])
        close_base = float(closes.iloc[-(self.lookback_days + 1)])

        if close_base == 0.0:
            return SignalResult(
                score=0.0,
                notes=[f"{ctx.symbol} base close price is zero — cannot compute momentum"],
            )

        momentum = close_now / close_base - 1.0

        if momentum < self.min_momentum_pct:
            return SignalResult(
                score=0.0,
                notes=[
                    f"{ctx.symbol} {self.lookback_days}d return {momentum:.2%} "
                    f"< threshold {self.min_momentum_pct:.2%} — no squeeze trigger "
                    f"(short_pct {short_pct:.1%} qualifies)"
                ],
            )

        # ------------------------------------------------------------------
        # Both conditions met → squeeze setup
        # ------------------------------------------------------------------
        return SignalResult(
            score=1.0,
            notes=[
                f"{ctx.symbol} squeeze setup: short_pct {short_pct:.1%} "
                f">= {self.min_short_pct:.1%} AND {self.lookback_days}d return {momentum:.2%} "
                f">= {self.min_momentum_pct:.2%}"
            ],
        )
