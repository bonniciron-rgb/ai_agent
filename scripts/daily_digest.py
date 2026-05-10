"""Convenience entry point for the daily digest job.

Delegates to ``ai_agent.digest.daily_digest`` which contains all the logic.
"""
import sys

from ai_agent.digest.daily_digest import main

if __name__ == "__main__":
    sys.exit(main())
