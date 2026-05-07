"""Backtest harness — bar-by-bar replay engine + baseline strategies + metrics."""

from ai_agent.backtest.engine import BacktestResult, Trade, run_backtest
from ai_agent.backtest.llm_strategy import LlmStrategy
from ai_agent.backtest.metrics import equity_from_benchmark, summary
from ai_agent.backtest.replay import build_replay_toolbox
from ai_agent.backtest.report import compare_strategies, format_report
from ai_agent.backtest.strategy import EmaBreakoutStrategy, SmaCrossStrategy, Strategy

__all__ = [
    "BacktestResult",
    "EmaBreakoutStrategy",
    "LlmStrategy",
    "SmaCrossStrategy",
    "Strategy",
    "Trade",
    "build_replay_toolbox",
    "compare_strategies",
    "equity_from_benchmark",
    "format_report",
    "run_backtest",
    "summary",
]
