"""Backtest performance metrics.

All functions consume a ``pd.Series`` of portfolio NAV values indexed by date.
They return plain Python scalars (floats / ints) so they're easy to serialise.

Benchmark comparison helpers expect two equity curves with (possibly) different
date ranges; they are aligned by inner-join before computing relative metrics.
"""

from __future__ import annotations

import math

import pandas as pd


def total_return(equity: pd.Series) -> float:
    """(final NAV / initial NAV) - 1, expressed as a fraction."""
    if len(equity) < 2:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0]) - 1.0


def cagr(equity: pd.Series) -> float:
    """Compound annual growth rate, assuming 252 trading days/year."""
    if len(equity) < 2:
        return 0.0
    years = len(equity) / 252.0
    if years <= 0:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    if total <= 0:
        return -1.0
    return float(total ** (1.0 / years)) - 1.0


def max_drawdown(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.25 = -25 %)."""
    if len(equity) < 2:
        return 0.0
    roll_max = equity.cummax()
    drawdowns = equity / roll_max - 1.0
    return float(drawdowns.min())


def sharpe_ratio(equity: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Annualised Sharpe ratio using daily returns, 252 trading days/year.

    Returns 0.0 when there are fewer than 2 bars or the std is zero.
    """
    if len(equity) < 2:
        return 0.0
    daily_returns = equity.pct_change().dropna()
    if len(daily_returns) == 0:
        return 0.0
    std = float(daily_returns.std())
    if std == 0.0 or math.isnan(std):
        return 0.0
    excess = daily_returns.mean() - risk_free_rate / 252.0
    return float(excess / std * math.sqrt(252))


def win_rate(trades: list) -> float:
    """Fraction of closed round-trips that were profitable.

    A round-trip is a buy followed by (one or more) sells that flatten the
    position.  Pairs are matched FIFO.  Returns 0.0 when there are no closed
    round-trips.
    """
    buy_prices: list[float] = []
    wins = 0
    total = 0

    for trade in trades:
        if trade.side == "buy":
            buy_prices.append(trade.price)
        elif trade.side == "sell" and buy_prices:
            entry = buy_prices.pop(0)
            total += 1
            if trade.price > entry:
                wins += 1

    return wins / total if total > 0 else 0.0


def volatility(equity: pd.Series) -> float:
    """Annualised daily-returns standard deviation."""
    if len(equity) < 2:
        return 0.0
    return float(equity.pct_change().dropna().std() * math.sqrt(252))


def summary(equity: pd.Series, trades: list, *, benchmark: pd.Series | None = None) -> dict:
    """Return a dict of key metrics, optionally with benchmark comparison."""
    result: dict = {
        "total_return": total_return(equity),
        "cagr": cagr(equity),
        "sharpe": sharpe_ratio(equity),
        "max_drawdown": max_drawdown(equity),
        "volatility": volatility(equity),
        "win_rate": win_rate(trades),
        "num_trades": len(trades),
        "bars": len(equity),
    }

    if benchmark is not None and len(benchmark) >= 2:
        result["benchmark_total_return"] = total_return(benchmark)
        result["benchmark_cagr"] = cagr(benchmark)
        result["benchmark_sharpe"] = sharpe_ratio(benchmark)
        result["benchmark_max_drawdown"] = max_drawdown(benchmark)
        # Alpha = strategy CAGR - benchmark CAGR (simple)
        result["alpha"] = result["cagr"] - result["benchmark_cagr"]

    return result


def equity_from_benchmark(
    benchmark_close: pd.Series,
    *,
    initial_capital: float = 10_000.0,
) -> pd.Series:
    """Convert a raw price series into a buy-and-hold NAV curve starting at *initial_capital*."""
    if benchmark_close.empty:
        return pd.Series(dtype=float)
    shares = initial_capital / float(benchmark_close.iloc[0])
    return (benchmark_close * shares).rename("equity")
