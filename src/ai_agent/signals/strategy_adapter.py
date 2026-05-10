"""Adapt a Signal to the existing Strategy protocol so run_backtest() can run it.

Long-only thresholding policy:
  - if position == 0 AND score >= entry_threshold: enter using all cash (whole shares)
  - if position > 0 AND (score < exit_threshold OR holding_days reached): exit
  - else: hold

Override entry/exit thresholds per backtest to tune sensitivity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ai_agent.signals.base import Signal, SignalContext


@dataclass
class SignalStrategy:
    signal: Signal
    symbol: str
    entry_threshold: float = 0.3
    exit_threshold: float = 0.0  # exit when score drops below this
    holding_days: int = 5
    warmup_bars: int = 50

    _bars_seen: list[dict] = field(default_factory=list, init=False)
    _held_days: int = field(default=0, init=False)

    def reset(self) -> None:
        self._bars_seen = []
        self._held_days = 0

    def on_bar(
        self,
        *,
        date: pd.Timestamp,
        row: pd.Series,
        position: int,
        cash: float,
    ) -> int:
        bar_date = date.date() if hasattr(date, "date") else date
        self._bars_seen.append(
            {
                "trading_date": bar_date,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            }
        )

        if len(self._bars_seen) < self.warmup_bars:
            return 0

        df = pd.DataFrame(self._bars_seen).set_index("trading_date")
        ctx = SignalContext(symbol=self.symbol, as_of=bar_date, bars=df)
        result = self.signal.compute(ctx)

        if position == 0:
            if result.score >= self.entry_threshold:
                close_price = float(row["close"])
                if close_price <= 0:
                    return 0
                qty = int(cash // close_price)
                return max(qty, 0)
            return 0

        # position > 0
        self._held_days += 1
        if result.score < self.exit_threshold or self._held_days >= self.holding_days:
            self._held_days = 0
            return -position
        return 0
