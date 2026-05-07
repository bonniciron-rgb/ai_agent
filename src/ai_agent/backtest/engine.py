"""Bar-by-bar backtest engine.

Processes a price DataFrame in chronological order, calling a Strategy on each
bar to receive order signals, then simulating fills at the next bar's open.
Tracks positions, cash, and a daily equity curve.

Design notes:
- One symbol at a time; multi-symbol callers loop externally.
- No fractional shares; quantities must be whole integers.
- Fills happen at next-bar open (avoids look-ahead on the signal bar).
- Short selling is not supported in V1; sell signals are capped at long qty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from ai_agent.backtest.strategy import Strategy


@dataclass(frozen=True)
class Trade:
    date: pd.Timestamp
    symbol: str
    side: str  # "buy" | "sell"
    qty: int
    price: float
    cash_after: float
    position_after: int


@dataclass
class BacktestResult:
    symbol: str
    equity_curve: pd.Series  # indexed by date, value = portfolio NAV
    trades: list[Trade] = field(default_factory=list)
    initial_capital: float = 10_000.0


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    *,
    symbol: str = "UNKNOWN",
    initial_capital: float = 10_000.0,
    commission: float = 0.001,  # 0.1 % per trade (round-trip = 0.2 %)
) -> BacktestResult:
    """Run a single-symbol backtest over *df*.

    Parameters
    ----------
    df:
        OHLCV DataFrame with at minimum columns ``open``, ``high``, ``low``,
        ``close``, ``volume`` and a DatetimeIndex (or date-convertible index).
    strategy:
        Any object satisfying the ``Strategy`` protocol.
    symbol:
        Ticker label used in result metadata.
    initial_capital:
        Starting cash in account currency.
    commission:
        Fractional commission applied to the notional value of every fill
        (buy *and* sell).

    Returns
    -------
    BacktestResult with an equity curve (NAV per bar) and trade log.
    """
    if df.empty:
        raise ValueError("Cannot run backtest on an empty DataFrame")

    df = df.sort_index()
    strategy.reset()

    cash = float(initial_capital)
    position = 0  # shares held (long only)
    equity: dict[pd.Timestamp, float] = {}
    trades: list[Trade] = []

    dates = df.index.tolist()

    for i, date in enumerate(dates):
        row = df.loc[date]

        # NAV at current close
        nav = cash + position * float(row["close"])
        equity[date] = nav

        # Ask strategy for a signal; signal is acted on at *next* bar open
        signal = strategy.on_bar(date=date, row=row, position=position, cash=cash)

        if signal == 0 or i + 1 >= len(dates):
            continue

        next_date = dates[i + 1]
        fill_price = float(df.loc[next_date, "open"])

        if signal > 0:  # buy
            affordable = int(cash // (fill_price * (1.0 + commission)))
            qty = min(signal, affordable)
            if qty <= 0:
                continue
            cost = qty * fill_price * (1.0 + commission)
            cash -= cost
            position += qty
            trades.append(
                Trade(
                    date=next_date,
                    symbol=symbol,
                    side="buy",
                    qty=qty,
                    price=fill_price,
                    cash_after=cash,
                    position_after=position,
                )
            )

        elif signal < 0:  # sell
            qty = min(-signal, position)  # can't sell more than held
            if qty <= 0:
                continue
            proceeds = qty * fill_price * (1.0 - commission)
            cash += proceeds
            position -= qty
            trades.append(
                Trade(
                    date=next_date,
                    symbol=symbol,
                    side="sell",
                    qty=qty,
                    price=fill_price,
                    cash_after=cash,
                    position_after=position,
                )
            )

    # Mark final NAV using last close
    last_date = dates[-1]
    equity[last_date] = cash + position * float(df.loc[last_date, "close"])

    equity_series = pd.Series(equity, name="equity")
    equity_series.index = pd.DatetimeIndex(equity_series.index)

    return BacktestResult(
        symbol=symbol,
        equity_curve=equity_series,
        trades=trades,
        initial_capital=initial_capital,
    )
