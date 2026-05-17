"""Per-proposal risk score (1 = lowest risk, 5 = highest risk).

A transparent, rule-based 1-5 score derived from measurable inputs — position
size vs NAV, price volatility (ATR), and stop-loss width — so the score
attached to a proposal is auditable rather than an opaque model number.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Risk-rail caps the position at 5% of NAV; these thresholds sit below it.
_SIZE_HIGH = Decimal("0.035")
_SIZE_MOD = Decimal("0.02")
_ATR_HIGH = Decimal("0.04")
_ATR_MOD = Decimal("0.02")
_STOP_WIDE = Decimal("0.10")
_STOP_MOD = Decimal("0.05")

_LABELS = {1: "Very low", 2: "Low", 3: "Moderate", 4: "High", 5: "Very high"}


@dataclass(frozen=True)
class RiskScore:
    """A 1-5 risk score and a short human-readable reason."""

    score: int  # 1 (lowest risk) .. 5 (highest)
    reason: str


def score_proposal(
    *,
    notional_gbp: Decimal,
    nav: Decimal,
    price: Decimal,
    atr: Decimal | None,
    stop_price: Decimal | None,
) -> RiskScore:
    """Score a single proposal 1-5 from measurable risk inputs.

    Three factors each contribute 0 (low), 1 (moderate) or 2 (high) points:
    position size vs NAV, ATR volatility, and stop-loss width. Missing data
    contributes a conservative non-zero amount rather than being ignored.
    """
    points = 0
    parts: list[str] = []

    if nav > 0:
        size_pct = notional_gbp / nav
        if size_pct > _SIZE_HIGH:
            points += 2
        elif size_pct >= _SIZE_MOD:
            points += 1
        parts.append(f"size {size_pct:.1%} of NAV")
    else:
        points += 1
        parts.append("NAV unknown")

    if atr is not None and price > 0:
        atr_pct = atr / price
        if atr_pct > _ATR_HIGH:
            points += 2
        elif atr_pct >= _ATR_MOD:
            points += 1
        parts.append(f"ATR {atr_pct:.1%}")
    else:
        points += 1
        parts.append("ATR unavailable")

    if stop_price is not None and price > 0:
        stop_pct = abs(price - stop_price) / price
        if stop_pct > _STOP_WIDE:
            points += 2
        elif stop_pct >= _STOP_MOD:
            points += 1
        parts.append(f"stop {stop_pct:.0%} from entry")
    else:
        points += 2
        parts.append("no stop set")

    score = _points_to_score(points)
    return RiskScore(score=score, reason=f"{_LABELS[score]} — " + ", ".join(parts))


def _points_to_score(points: int) -> int:
    if points <= 0:
        return 1
    if points <= 2:
        return 2
    if points == 3:
        return 3
    if points <= 5:
        return 4
    return 5
