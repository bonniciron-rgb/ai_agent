"""Convenience entry point for the nightly reconciliation job.

Delegates to ``ai_agent.reconciliation`` which contains all the logic.

Run::

    python scripts/reconcile.py
    # or
    python -m ai_agent.reconciliation
"""

import sys

from ai_agent.reconciliation import main

if __name__ == "__main__":
    sys.exit(main())
