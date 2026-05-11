"""Signal validation harness.

Pluggable Signal interface + a Strategy adapter so any signal can be
backtested with the existing run_backtest() engine.  No live integration
yet — see the C1 PR description.
"""

from ai_agent.signals.analyst_revisions import (
    AnalystRevisionMomentumSignal,
    RecommendationSnapshot,
)
from ai_agent.signals.base import Signal, SignalContext, SignalResult
from ai_agent.signals.pead import EarningsEvent, PostEarningsDriftSignal
from ai_agent.signals.reference import AlwaysFlatSignal, SmaCrossSignal
from ai_agent.signals.runner import (
    SignalBacktestSummary,
    backtest_signal,
    save_backtest_result,
)
from ai_agent.signals.sector_rs import SectorRelativeStrengthSignal
from ai_agent.signals.strategy_adapter import SignalStrategy

__all__ = [
    "AlwaysFlatSignal",
    "AnalystRevisionMomentumSignal",
    "EarningsEvent",
    "PostEarningsDriftSignal",
    "RecommendationSnapshot",
    "SectorRelativeStrengthSignal",
    "Signal",
    "SignalBacktestSummary",
    "SignalContext",
    "SignalResult",
    "SignalStrategy",
    "SmaCrossSignal",
    "backtest_signal",
    "save_backtest_result",
]
