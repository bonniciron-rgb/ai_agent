"""Convenience entry point for the daily quant-signal snapshot job.

Delegates to ``ai_agent.signals.snapshot_job``. Designed to run on a cron a
little before the daily trade loop so the agent's ``get_quant_signals`` tool
has fresh data. Safe to run repeatedly — snapshots upsert per (symbol, day).

Run::

    python scripts/compute_signals.py
    python scripts/compute_signals.py --dry-run
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_agent.signals.snapshot_job import main

if __name__ == "__main__":
    sys.exit(main())
