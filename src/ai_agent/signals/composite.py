"""Composite factor blend — v3 strategic pivot signal.

Combines multiple sub-signals (typically A1 sector RS, A2 PEAD, B2 analyst
revision momentum) into a continuous weighted-average score. Designed for the
exposure-manager use case: rather than driving binary buy/sell decisions on
individual stocks, the composite score modulates portfolio allocation (e.g.,
50-150% SPY tilt).

Background:
    After 2 real-data backtest runs (v1 + v2, 2026-05-11), no single signal
    in our library produced positive alpha vs SPY over 4 years (2022-2026).
    The composite approach is the "multi-factor blend" alternative to
    single-signal alpha discovery — broadly the same technique used by
    risk-premia funds (AQR, BlackRock, Dimensional), where the goal is
    capturing modest persistent factor premiums rather than finding hidden
    edge.

Score semantics:
    Each sub-signal is asked to compute() for the same SignalContext, and
    the composite returns a weighted-average score. Sub-signals returning
    0.0 (no data, no qualifying event) are treated as "no contribution"
    rather than "abstain" — that's a conservative choice: a missing factor
    cannot generate exposure.

    With 3 binary (0.0 / 1.0) sub-signals and equal weights, the composite
    score takes one of 4 values: 0.0, 0.33, 0.67, 1.0. Strategy adapters
    consuming this score can then map to position size (e.g., 0% / 33% /
    67% / 100% of available capital), giving meaningful exposure
    differentiation that the individual binary signals cannot.

    Sub-signals may also return continuous scores in [0.0, 1.0]; the
    composite passes that through unchanged.

Long-only convention:
    All current sub-signals are long-only (score in [0.0, 1.0]). The
    composite does not add a short leg — that's reserved for a future
    variant that takes both bullish and bearish sub-signals.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_agent.signals.base import Signal, SignalContext, SignalResult


class CompositeFactorSignal:
    """Blend multiple sub-signals into a continuous composite score.

    Parameters
    ----------
    sub_signals:
        Iterable of sub-signal instances. Each must conform to the
        :class:`Signal` protocol (have ``name``, ``version``, ``compute()``).
    weights:
        Optional per-sub-signal weights. If provided, must have the same
        length as ``sub_signals``. Defaults to equal weights (all 1.0).
        Weights need not sum to 1 — they are normalised internally.
    name_suffix:
        Optional suffix appended to the signal name (useful when running
        multiple composites with different weights in the same backtest).
    """

    name = "composite_factor"
    version = "0.1.0"

    def __init__(
        self,
        sub_signals: Sequence[Signal],
        weights: Sequence[float] | None = None,
        *,
        name_suffix: str = "",
    ) -> None:
        if not sub_signals:
            raise ValueError("CompositeFactorSignal requires at least one sub-signal")

        self.sub_signals: list[Signal] = list(sub_signals)

        if weights is None:
            self.weights: list[float] = [1.0] * len(self.sub_signals)
        else:
            if len(weights) != len(self.sub_signals):
                raise ValueError(
                    f"len(weights)={len(weights)} must equal len(sub_signals)="
                    f"{len(self.sub_signals)}"
                )
            self.weights = [float(w) for w in weights]

        self._weight_sum = sum(self.weights)
        if self._weight_sum <= 0.0:
            raise ValueError("Sum of weights must be positive")

        if name_suffix:
            self.name = f"composite_factor_{name_suffix}"

    def compute(self, ctx: SignalContext) -> SignalResult:
        """Compute the weighted-average score across all sub-signals."""
        weighted_sum = 0.0
        note_parts: list[str] = []

        for sig, w in zip(self.sub_signals, self.weights, strict=True):
            sub_result = sig.compute(ctx)
            weighted_sum += sub_result.score * w
            note_parts.append(f"{sig.name}={sub_result.score:.2f}*{w:.2f}")

        composite_score = weighted_sum / self._weight_sum

        return SignalResult(
            score=composite_score,
            notes=[
                f"composite={composite_score:.3f} | " + " | ".join(note_parts),
            ],
        )
