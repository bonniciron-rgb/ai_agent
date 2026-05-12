"""Convenience entry point for the daily exposure-manager tilt job.

Delegates to ``ai_agent.exposure.job`` which contains all the logic.
"""

import sys

from ai_agent.exposure.job import main

if __name__ == "__main__":
    sys.exit(main())
