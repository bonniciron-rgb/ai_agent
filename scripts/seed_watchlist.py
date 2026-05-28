"""One-shot: upsert config/watchlist.yaml entries into the DB watchlist.

`bootstrap_from_yaml` only seeds the DB when the watchlist table is empty,
so edits to config/watchlist.yaml never reach an already-seeded prod DB.
This script closes that gap: it idempotently adds every YAML entry that is
missing from the DB (via `watchlist_store.add_entry`, which is a no-op for
symbols that already exist).

It only ADDS — it never deletes or un-pauses. A symbol you removed via the
Telegram/web editor that is still present in the YAML WILL be re-added, so
keep the YAML in sync with intended state.

Defaults to a dry-run listing what would change; pass `--apply` to commit.

Usage::

    python scripts/seed_watchlist.py            # dry-run
    python scripts/seed_watchlist.py --apply     # commit additions
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_agent.db.engine import init_schema
from ai_agent.db.watchlist_store import add_entry, list_entries
from ai_agent.loop.daily_loop import WATCHLIST_PATH
from ai_agent.watchlist import load_watchlist

logger = logging.getLogger("seed_watchlist")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit additions (default: dry-run)")
    parser.add_argument(
        "--path",
        default=str(WATCHLIST_PATH),
        help="Watchlist YAML path (default: config/watchlist.yaml)",
    )
    args = parser.parse_args(argv)

    init_schema()
    desired = load_watchlist(args.path)
    existing = {row.symbol.upper() for row in list_entries()}

    missing = [e for e in desired.entries if e.symbol.upper() not in existing]
    if not missing:
        logger.info("DB already has all %d YAML symbol(s); nothing to add", len(desired.entries))
        return 0

    for e in missing:
        logger.info("  + %-6s %s", e.symbol, e.sector or "(no sector)")
    logger.info("%d symbol(s) missing from DB", len(missing))

    if not args.apply:
        logger.info("Dry-run: rerun with --apply to add them")
        return 0

    for e in missing:
        add_entry(symbol=e.symbol, sector=e.sector, notes=e.notes, tags=e.tags)
    logger.info("Added %d symbol(s) to the DB watchlist", len(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
