"""Backtest harness — bar-by-bar replay engine + baseline strategies + metrics."""

from ai_agent.backtest.engine import BacktestResult, Trade, run_backtest
from ai_agent.backtest.metrics import equity_from_benchmark, summary
from ai_agent.backtest.strategy import EmaBreakoutStrategy, SmaCrossStrategy, Strategy

__all__ = [
    "BacktestResult",
    "EmaBreakoutStrategy",
    "SmaCrossStrategy",
    "Strategy",
    "Trade",
    "equity_from_benchmark",
    "run_backtest",
    "summary",
]
