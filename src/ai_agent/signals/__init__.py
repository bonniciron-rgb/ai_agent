"""Signal validation harness.

Pluggable Signal interface + a Strategy adapter so any signal can be
backtested with the existing run_backtest() engine.

v3 strategic pivot (2026-05-11): A3 (insider) and B5 (short squeeze) removed
from public API after backtests showed broken data fetching (A3) and
catastrophic falling-knife loss (-0.90 Sharpe on B5). Source files retained
in ``insider_buying.py`` and ``short_interest.py`` for future revival if
better data sources become available.

Active signals: A1 (sector RS), A2 (PEAD), B2 (analyst revisions),
plus the CompositeFactorSignal that blends them.
"""

from ai_agent.signals.analyst_revisions import (
    AnalystRevisionMomentumSignal,
    RecommendationSnapshot,
)
from ai_agent.signals.base import Signal, SignalContext, SignalResult
from ai_agent.signals.composite import CompositeFactorSignal
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
    "CompositeFactorSignal",
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
