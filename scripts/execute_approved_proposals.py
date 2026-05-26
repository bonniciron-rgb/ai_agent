"""Convenience entry point for the approved-proposal execution worker.

Delegates to ``ai_agent.broker.execute_approved``. Designed to be invoked
by the GitHub Actions cron in ``.github/workflows/execute-approved.yml``
or manually for testing.

Run::

    python scripts/execute_approved_proposals.py
    python scripts/execute_approved_proposals.py --dry-run
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_agent.broker.execute_approved import main

if __name__ == "__main__":
    sys.exit(main())
