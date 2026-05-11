"""A1: Sector Relative-Strength Signal — first real alpha signal through C1 harness.

Goes long when a stock's 20-day return exceeds its sector ETF's 20-day return by a
configurable threshold.  Long-only; flat otherwise.  No short positions.
"""

from __future__ import annotations

import pandas as pd

from ai_agent.signals.base import SignalContext, SignalResult

_DEFAULT_LOOKBACK = 20
_DEFAULT_THRESHOLD = 0.02  # 2 percentage points
_DEFAULT_ETF = "SPY"


class SectorRelativeStrengthSignal:
    """Long when stock outperforms its sector ETF over *lookback* trading days.

    Parameters
    ----------
    sector_map:
        Mapping of symbol → sector ETF ticker.  Symbols absent from the map
        fall back to *default_etf* (default: "SPY").
    sector_prices:
        Pre-fetched closing prices for each ETF ticker, keyed by ticker.
        Each value is a ``pd.Series`` indexed by date (matching the
        ``trading_date`` index used in ``SignalContext.bars``).
        The runner / test setup is responsible for fetching these; the signal
        itself performs no I/O.
    lookback:
        Rolling window in trading days for the return calculation.  Default 20.
    threshold:
        Minimum excess return (stock - sector ETF) required to go long.
        Default 0.02 (= 2 percentage points).
    default_etf:
        Fallback ETF ticker for symbols not in *sector_map*.  Default "SPY".
    """

    name = "sector_relative_strength"
    version = "v1"

    def __init__(
        self,
        *,
        sector_map: dict[str, str] | None = None,
        sector_prices: dict[str, pd.Series] | None = None,
        lookback: int = _DEFAULT_LOOKBACK,
        threshold: float = _DEFAULT_THRESHOLD,
        default_etf: str = _DEFAULT_ETF,
    ) -> None:
        self.sector_map: dict[str, str] = sector_map or {}
        self.sector_prices: dict[str, pd.Series] = sector_prices or {}
        self.lookback = lookback
        self.threshold = threshold
        self.default_etf = default_etf

    def compute(self, ctx: SignalContext) -> SignalResult:
        """Return ``score=1.0`` when stock beats its sector ETF, ``0.0`` otherwise."""
        if len(ctx.bars) < self.lookback + 1:
            return SignalResult(score=0.0, notes=["insufficient history"])

        close = ctx.bars["close"]
        stock_return = (close.iloc[-1] - close.iloc[-(self.lookback + 1)]) / close.iloc[
            -(self.lookback + 1)
        ]

        etf_ticker = self.sector_map.get(ctx.symbol, self.default_etf)
        etf_series = self.sector_prices.get(etf_ticker)

        if etf_series is None or etf_series.empty:
            return SignalResult(
                score=0.0,
                notes=[f"no sector prices for {etf_ticker}"],
            )

        # Align the ETF series to the stock's date index; keep only dates we have
        etf_aligned = etf_series.reindex(close.index)
        if etf_aligned.isna().any():
            # Forward-fill any missing ETF dates (holidays etc.)
            etf_aligned = etf_aligned.ffill()

        if len(etf_aligned) < self.lookback + 1 or pd.isna(etf_aligned.iloc[-(self.lookback + 1)]):
            return SignalResult(score=0.0, notes=["insufficient sector history"])

        etf_start = etf_aligned.iloc[-(self.lookback + 1)]
        etf_end = etf_aligned.iloc[-1]
        if etf_start == 0:
            return SignalResult(score=0.0, notes=["sector ETF price is zero"])

        etf_return = (etf_end - etf_start) / etf_start
        excess = float(stock_return) - float(etf_return)

        if excess >= self.threshold:
            return SignalResult(
                score=1.0,
                notes=[
                    f"{ctx.symbol} {self.lookback}d return {stock_return * 100:.2f}% "
                    f"vs {etf_ticker} {etf_return * 100:.2f}% "
                    f"(excess {excess * 100:.2f}% >= threshold {self.threshold * 100:.2f}%)"
                ],
            )

        return SignalResult(
            score=0.0,
            notes=[
                f"{ctx.symbol} {self.lookback}d return {stock_return * 100:.2f}% "
                f"vs {etf_ticker} {etf_return * 100:.2f}% "
                f"(excess {excess * 100:.2f}% < threshold {self.threshold * 100:.2f}%)"
            ],
        )
