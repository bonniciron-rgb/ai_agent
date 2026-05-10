"""Convenience entry point for the daily macro-regime detector.

Delegates to ``ai_agent.macro.regime_detector`` which contains all the logic.
"""

import sys

from ai_agent.macro.regime_detector import main

if __name__ == "__main__":
    sys.exit(main())
