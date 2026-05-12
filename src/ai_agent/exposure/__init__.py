"""Exposure-manager layer — Phase B of the v3 strategic pivot.

Turns the composite factor signal into a *current* SPY allocation decision
(50-100% in backtest, 50-150% live with margin), plus a human-readable
summary for the daily Telegram digest and the tilt dashboard.
"""

from ai_agent.exposure.tilt import (
    TiltSnapshot,
    compute_tilt_snapshot,
    score_to_allocation,
    tilt_summary_line,
)

__all__ = [
    "TiltSnapshot",
    "compute_tilt_snapshot",
    "score_to_allocation",
    "tilt_summary_line",
]
