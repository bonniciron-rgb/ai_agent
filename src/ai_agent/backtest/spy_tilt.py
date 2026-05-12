"""SPY-tilt exposure manager — Phase B of the v3 strategic pivot.

Rather than picking individual stocks, this strategy uses a composite signal
score across a stock universe to modulate the fraction of capital held in SPY:

    target_alloc = min_alloc + score * (max_alloc - min_alloc)

Example with min_alloc=0.5, max_alloc=1.0:
    score=0.0  →  50% in SPY  (defensive)
    score=0.5  →  75% in SPY  (neutral)
    score=1.0  → 100% in SPY  (fully deployed)

In live trading with a margin-enabled account, max_alloc can be set to 1.5 to
achieve the 50-150% SPY tilt described in etheratrading.md. In the backtest
engine (long-only, no leverage) max_alloc is capped at 1.0.

Score computation:
    The signal (typically CompositeFactorSignal) is evaluated for each universe
    symbol at each date, and the results are averaged. This portfolio-level
    aggregation is pre-computed in reset() for efficiency — O(dates x symbols)
    up-front rather than O(1) per bar with O(bars) lookback slicing.

Rebalancing:
    A position is only adjusted when the gap between current and target
    allocation exceeds rebalance_threshold (default 5%). This avoids
    excessive turnover and commission drag from small score fluctuations.
"""

from __future__ import annotations

import pandas as pd

from ai_agent.signals.base import Signal, SignalContext


class SpyTiltStrategy:
    """Rebalance SPY allocation based on composite score averaged across a universe.

    Parameters
    ----------
    signal:
        Any Signal (typically CompositeFactorSignal). Evaluated per symbol.
    universe_bars:
        Mapping of symbol → OHLCV DataFrame. Used to compute per-symbol
        signal scores which are then averaged to produce the portfolio score.
    min_alloc:
        Minimum SPY allocation fraction when score=0.0 (default 0.5 = 50%).
    max_alloc:
        Maximum SPY allocation fraction when score=1.0 (default 1.0 = 100%).
        For live trading with margin, set to 1.5; backtest engine caps at 1.0.
    rebalance_threshold:
        Only rebalance when |target_alloc - current_alloc| >= this value.
        Prevents commission drag from micro-adjustments (default 0.05 = 5%).
    warmup_bars:
        Number of SPY bars to skip before the first rebalance decision.
    """

    def __init__(
        self,
        signal: Signal,
        universe_bars: dict[str, pd.DataFrame],
        *,
        min_alloc: float = 0.5,
        max_alloc: float = 1.0,
        rebalance_threshold: float = 0.05,
        warmup_bars: int = 50,
    ) -> None:
        if not (0.0 <= min_alloc <= max_alloc):
            raise ValueError(
                f"min_alloc={min_alloc} must satisfy 0 <= min_alloc <= max_alloc={max_alloc}"
            )
        if rebalance_threshold < 0.0:
            raise ValueError("rebalance_threshold must be non-negative")

        self._signal = signal
        self._universe_bars = {sym: df.copy() for sym, df in universe_bars.items()}
        self._min_alloc = min_alloc
        self._max_alloc = max_alloc
        self._rebalance_threshold = rebalance_threshold
        self._warmup_bars = warmup_bars

        self._score_by_date: dict = {}
        self._bars_seen: int = 0

    # ------------------------------------------------------------------
    # Strategy protocol
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._score_by_date = self._compute_score_series()
        self._bars_seen = 0

    def on_bar(
        self,
        *,
        date: pd.Timestamp,
        row: pd.Series,
        position: int,
        cash: float,
    ) -> int:
        self._bars_seen += 1
        if self._bars_seen < self._warmup_bars:
            return 0

        bar_date = date.date() if hasattr(date, "date") else date
        score = self._score_by_date.get(bar_date, 0.0)
        target_alloc = self._min_alloc + score * (self._max_alloc - self._min_alloc)

        close = float(row["close"])
        if close <= 0:
            return 0

        nav = cash + position * close
        if nav <= 0:
            return 0

        current_alloc = (position * close) / nav
        if abs(target_alloc - current_alloc) < self._rebalance_threshold:
            return 0

        target_qty = int(nav * target_alloc / close)
        return target_qty - position

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_score_series(self) -> dict:
        """Pre-compute average composite score across universe for every date.

        Only dates with at least one symbol having >= warmup_bars history
        produce a score; all other dates fall back to 0.0 in on_bar().
        """
        if not self._universe_bars:
            return {}

        sym_bars_dt: dict[str, pd.DataFrame] = {}
        for sym, bars in self._universe_bars.items():
            b = bars.copy()
            b.index = pd.to_datetime(b.index)
            b = b.sort_index()
            sym_bars_dt[sym] = b

        all_dates = sorted({d for bars in sym_bars_dt.values() for d in bars.index.date})

        scores: dict = {}
        for d in all_dates:
            sym_scores: list[float] = []
            for sym, bars in sym_bars_dt.items():
                bars_up = bars[bars.index.date <= d]
                if len(bars_up) < self._warmup_bars:
                    continue
                ctx = SignalContext(symbol=sym, as_of=d, bars=bars_up)
                try:
                    r = self._signal.compute(ctx)
                    sym_scores.append(r.score)
                except Exception:
                    pass
            if sym_scores:
                scores[d] = sum(sym_scores) / len(sym_scores)

        return scores
