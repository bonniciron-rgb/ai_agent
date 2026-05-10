"""Backfill historical OHLCV bars for every symbol in the watchlist.

Usage:
    python scripts/backfill_watchlist.py [--years N] [--symbol SYM]

Examples:
    python scripts/backfill_watchlist.py --years 5          # all 14 tickers, 5 yr
    python scripts/backfill_watchlist.py --years 2 --symbol NVDA  # one ticker
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running directly from the repo root without editable install
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_agent.data.registry import OhlcvChain
from ai_agent.data.stooq_source import StooqSource
from ai_agent.data.yfinance_source import YFinanceSource
from ai_agent.db.engine import init_schema
from ai_agent.loop.bar_store import ingest_bars
from ai_agent.watchlist import load_watchlist

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("backfill")

WATCHLIST_PATH = Path(__file__).parent.parent / "config" / "watchlist.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill OHLCV bars from watchlist")
    parser.add_argument(
        "--years",
        type=float,
        default=5.0,
        help="Number of years of history to fetch (default: 5)",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Backfill a single symbol instead of the full watchlist",
    )
    args = parser.parse_args()

    days_back = int(args.years * 365)

    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        watchlist = load_watchlist(WATCHLIST_PATH)
        symbols = watchlist.symbols

    logger.info(
        "Backfilling %d symbol(s) — %g years (%d days): %s",
        len(symbols),
        args.years,
        days_back,
        ", ".join(symbols),
    )

    init_schema()

    source = OhlcvChain([YFinanceSource(), StooqSource()])

    total = ingest_bars(symbols, source=source, days_back=days_back)
    logger.info("Done — inserted %d new bars total.", total)


if __name__ == "__main__":
    main()
