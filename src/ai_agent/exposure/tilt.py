"""Current-tilt computation shared by the dashboard and the daily digest.

The backtest's :class:`~ai_agent.backtest.spy_tilt.SpyTiltStrategy` answers
"what allocation would I have held on each historical bar?". This module
answers "what allocation should I hold *right now*?" — using the latest bar
of each universe symbol — and packages the answer (plus the per-symbol score
breakdown) for display.

Score → allocation mapping is identical to the backtest's, via the shared
:func:`score_to_allocation` helper, so dashboard/digest and backtest never
disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ai_agent.signals.base import Signal, SignalContext


def score_to_allocation(
    score: float,
    *,
    min_alloc: float = 0.5,
    max_alloc: float = 1.0,
    score_floor: float = 0.0,
    score_ceiling: float = 1.0,
) -> float:
    """Map a composite score to a target allocation fraction.

    ``norm = clamp((score - score_floor) / (score_ceiling - score_floor), 0, 1)``
    then ``min_alloc + norm * (max_alloc - min_alloc)``. Raises if the band is
    degenerate.
    """
    if score_floor >= score_ceiling:
        raise ValueError(f"score_floor={score_floor} must be < score_ceiling={score_ceiling}")
    if not (0.0 <= min_alloc <= max_alloc):
        raise ValueError(
            f"min_alloc={min_alloc} must satisfy 0 <= min_alloc <= max_alloc={max_alloc}"
        )
    norm = (score - score_floor) / (score_ceiling - score_floor)
    norm = max(0.0, min(1.0, norm))
    return min_alloc + norm * (max_alloc - min_alloc)


@dataclass
class TiltSnapshot:
    """The current exposure decision plus the inputs that produced it."""

    as_of: date
    composite_score: float  # universe-average composite score, raw
    target_allocation: float  # fraction of capital to hold in SPY (e.g. 0.65)
    n_symbols: int  # how many universe symbols had enough history to score
    per_symbol_scores: dict[str, float] = field(default_factory=dict)
    min_alloc: float = 0.5
    max_alloc: float = 1.0
    score_ceiling: float = 1.0

    @property
    def allocation_pct(self) -> int:
        """Target allocation as a rounded percentage (for display)."""
        return round(self.target_allocation * 100)


def compute_tilt_snapshot(
    composite_signal: Signal,
    universe_bars: dict[str, pd.DataFrame],
    *,
    as_of: date | None = None,
    min_alloc: float = 0.5,
    max_alloc: float = 1.0,
    score_ceiling: float = 1.0,
    warmup_bars: int = 50,
) -> TiltSnapshot:
    """Evaluate *composite_signal* on the latest bar of each symbol and aggregate.

    Symbols with fewer than ``warmup_bars`` rows (or empty data) are skipped.
    If no symbol qualifies, the snapshot has ``composite_score=0.0`` and the
    allocation falls to ``min_alloc`` (defensive).

    ``as_of`` defaults to the most recent date present across the universe.
    """
    per_symbol: dict[str, float] = {}
    latest_dates: list[date] = []

    for sym, bars in universe_bars.items():
        if bars is None or bars.empty:
            continue
        b = bars.copy()
        b.index = pd.to_datetime(b.index)
        b = b.sort_index()
        if len(b) < warmup_bars:
            continue
        sym_as_of = b.index[-1].date()
        latest_dates.append(sym_as_of)
        ctx = SignalContext(symbol=sym, as_of=sym_as_of, bars=b)
        try:
            result = composite_signal.compute(ctx)
            per_symbol[sym] = float(result.score)
        except Exception:
            continue

    resolved_as_of = as_of or (max(latest_dates) if latest_dates else date.today())
    composite_score = sum(per_symbol.values()) / len(per_symbol) if per_symbol else 0.0
    target = score_to_allocation(
        composite_score,
        min_alloc=min_alloc,
        max_alloc=max_alloc,
        score_ceiling=score_ceiling,
    )

    return TiltSnapshot(
        as_of=resolved_as_of,
        composite_score=composite_score,
        target_allocation=target,
        n_symbols=len(per_symbol),
        per_symbol_scores=per_symbol,
        min_alloc=min_alloc,
        max_alloc=max_alloc,
        score_ceiling=score_ceiling,
    )


def tilt_summary_line(snapshot: TiltSnapshot, *, prev_allocation: float | None = None) -> str:
    """One-line summary for the daily Telegram digest.

    Example: ``"Tilt: 65% SPY (composite +0.09, 11 names) — up 5pp from yesterday"``
    """
    parts = [
        f"Tilt: {snapshot.allocation_pct}% SPY",
        f"(composite {snapshot.composite_score:+.2f}, {snapshot.n_symbols} names)",
    ]
    if prev_allocation is not None:
        delta_pp = round((snapshot.target_allocation - prev_allocation) * 100)
        if delta_pp > 0:
            parts.append(f"— up {delta_pp}pp from yesterday")
        elif delta_pp < 0:
            parts.append(f"— down {abs(delta_pp)}pp from yesterday")
        else:
            parts.append("— unchanged from yesterday")
    return " ".join(parts)
