"""CLI to backtest a registered signal and optionally persist the result.

Usage::

    python scripts/backtest_signal.py \\
        --signal sma_cross \\
        --symbols AAPL,MSFT,GOOG \\
        --start 2023-01-01 --end 2025-12-31 \\
        --save
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_agent.db.engine import init_schema
from ai_agent.signals import (
    AlwaysFlatSignal,
    AnalystRevisionMomentumSignal,
    InsiderBuyingSignal,
    PostEarningsDriftSignal,
    SectorRelativeStrengthSignal,
    SmaCrossSignal,
    backtest_signal,
    save_backtest_result,
)

REGISTRY = {
    "always_flat": AlwaysFlatSignal,
    "analyst_revision_momentum": AnalystRevisionMomentumSignal,
    "insider_buying": InsiderBuyingSignal,
    "post_earnings_drift": PostEarningsDriftSignal,
    "sector_relative_strength": SectorRelativeStrengthSignal,
    "sma_cross": SmaCrossSignal,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal", required=True, choices=sorted(REGISTRY))
    parser.add_argument("--symbols", required=True, help="Comma-separated tickers")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--capital", default="10000", type=str)
    parser.add_argument("--entry-threshold", default=0.3, type=float)
    parser.add_argument("--holding-days", default=5, type=int)
    parser.add_argument("--save", action="store_true", help="Persist a SignalBacktest row")
    parser.add_argument(
        "--sector-map",
        default=None,
        help="Path to JSON file mapping symbol→sector ETF (for sector_relative_strength signal). "
        'Example: \'{"AAPL": "XLK", "JPM": "XLF"}\'',
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.save:
        init_schema()

    kwargs: dict = {}
    if args.signal == "sector_relative_strength" and args.sector_map:
        with open(args.sector_map) as fh:
            kwargs["sector_map"] = json.load(fh)

    signal = REGISTRY[args.signal](**kwargs)
    result = backtest_signal(
        signal,
        symbols=[s.strip().upper() for s in args.symbols.split(",")],
        start=datetime.strptime(args.start, "%Y-%m-%d").date(),
        end=datetime.strptime(args.end, "%Y-%m-%d").date(),
        benchmark_symbol=args.benchmark,
        initial_capital=float(args.capital),
        entry_threshold=args.entry_threshold,
        holding_days=args.holding_days,
    )

    out = {
        "signal_name": result.signal_name,
        "signal_version": result.signal_version,
        "period": [result.period_start.isoformat(), result.period_end.isoformat()],
        "symbols": result.symbols,
        "metrics": {
            "sharpe": result.sharpe,
            "cagr": result.cagr,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "alpha": result.alpha,
            "trade_count": result.trade_count,
        },
        "benchmark": {
            "symbol": result.benchmark_symbol,
            "sharpe": result.benchmark_sharpe,
            "cagr": result.benchmark_cagr,
        },
        "per_symbol": result.per_symbol,
    }
    print(json.dumps(out, indent=2, default=str))

    if args.save:
        row = save_backtest_result(result)
        print(f"\nSaved as SignalBacktest id={row.id}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
