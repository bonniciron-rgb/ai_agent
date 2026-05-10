"""Reference signals — used to prove the harness works.

These are NOT real alpha signals.  AlwaysFlatSignal exists for sanity tests
(zero trades, zero return).  SmaCrossSignal is a trivial 50/200-SMA crossover
that produces non-zero behavior on trending data — useful as a smoke test.
"""

from __future__ import annotations

from ai_agent.signals.base import SignalContext, SignalResult


class AlwaysFlatSignal:
    """Always returns score=0 — should produce zero trades."""

    name = "always_flat"
    version = "v1"

    def compute(self, ctx: SignalContext) -> SignalResult:
        return SignalResult(score=0.0, confidence=0.0, notes=["reference: flat"])


class SmaCrossSignal:
    """Bullish when 50d SMA > 200d SMA (golden cross structure)."""

    name = "sma_cross"
    version = "v1"

    def __init__(self, fast: int = 50, slow: int = 200):
        self.fast = fast
        self.slow = slow

    def compute(self, ctx: SignalContext) -> SignalResult:
        if len(ctx.bars) < self.slow:
            return SignalResult(score=0.0, notes=["insufficient data"])

        close = ctx.bars["close"]
        sma_fast = close.rolling(self.fast).mean().iloc[-1]
        sma_slow = close.rolling(self.slow).mean().iloc[-1]

        if sma_fast > sma_slow:
            spread_pct = (sma_fast - sma_slow) / sma_slow
            score = float(min(1.0, spread_pct * 20))  # scale: 5% spread = score 1.0
            return SignalResult(score=score, notes=[f"50d > 200d by {spread_pct * 100:.2f}%"])

        return SignalResult(score=-0.5, notes=["50d < 200d"])
