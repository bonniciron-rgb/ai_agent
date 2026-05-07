"""Strategy protocol and built-in baseline strategies.

A Strategy must implement two methods:
- ``reset()``    : called once before the backtest loop begins.
- ``on_bar(...)`` : called for every bar; returns an integer signal:
      > 0 → buy that many shares
      < 0 → sell that many shares (or close position if abs > held)
      = 0 → hold / no action

Strategies receive the *current* bar's data and current position; they must
**not** read future bars.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from ai_agent.features.indicators import ema, sma


@runtime_checkable
class Strategy(Protocol):
    def reset(self) -> None: ...

    def on_bar(
        self,
        *,
        date: pd.Timestamp,
        row: pd.Series,
        position: int,
        cash: float,
    ) -> int: ...


class SmaCrossStrategy:
    """Classic dual-SMA crossover baseline.

    Goes long when the fast SMA crosses above the slow SMA, exits when it
    crosses back below.  The SMA series are pre-computed on ``__init__`` so
    ``on_bar`` is O(1) per call.

    Parameters
    ----------
    close:
        Full close-price series for the symbol being tested.
    fast:
        Fast SMA window (default 50).
    slow:
        Slow SMA window (default 200).
    shares_per_trade:
        Fixed lot size.  ``None`` → use all available cash at entry (full
        allocation, single position).
    """

    def __init__(
        self,
        close: pd.Series,
        *,
        fast: int = 50,
        slow: int = 200,
        shares_per_trade: int | None = None,
    ) -> None:
        self._fast_sma = sma(close, fast)
        self._slow_sma = sma(close, slow)
        self._shares_per_trade = shares_per_trade
        self._prev_above: bool | None = None

    def reset(self) -> None:
        self._prev_above = None

    def on_bar(
        self,
        *,
        date: pd.Timestamp,
        row: pd.Series,
        position: int,
        cash: float,
    ) -> int:
        fast_val = self._fast_sma.get(date)
        slow_val = self._slow_sma.get(date)

        if fast_val is None or slow_val is None or pd.isna(fast_val) or pd.isna(slow_val):
            return 0

        currently_above = float(fast_val) > float(slow_val)

        if self._prev_above is None:
            self._prev_above = currently_above
            return 0

        signal = 0
        if currently_above and not self._prev_above:
            # golden cross → buy
            if position == 0:
                if self._shares_per_trade is not None:
                    signal = self._shares_per_trade
                else:
                    # full allocation: buy as many shares as cash allows
                    price = float(row["close"])
                    signal = max(1, int(cash // price)) if price > 0 else 1
        elif not currently_above and self._prev_above and position > 0:
            signal = -position

        self._prev_above = currently_above
        return signal


class EmaBreakoutStrategy:
    """Price-crosses-EMA momentum strategy (useful for fast-moving assets).

    Enters long when close crosses above the EMA; exits when it crosses below.
    """

    def __init__(
        self,
        close: pd.Series,
        *,
        period: int = 20,
        shares_per_trade: int | None = None,
    ) -> None:
        self._ema = ema(close, period)
        self._shares_per_trade = shares_per_trade
        self._prev_above: bool | None = None

    def reset(self) -> None:
        self._prev_above = None

    def on_bar(
        self,
        *,
        date: pd.Timestamp,
        row: pd.Series,
        position: int,
        cash: float,
    ) -> int:
        ema_val = self._ema.get(date)
        if ema_val is None or pd.isna(ema_val):
            return 0

        currently_above = float(row["close"]) > float(ema_val)

        if self._prev_above is None:
            self._prev_above = currently_above
            return 0

        signal = 0
        if currently_above and not self._prev_above:
            if position == 0:
                price = float(row["close"])
                signal = (
                    self._shares_per_trade
                    if self._shares_per_trade is not None
                    else max(1, int(cash // price))
                )
        elif not currently_above and self._prev_above and position > 0:
            signal = -position

        self._prev_above = currently_above
        return signal
