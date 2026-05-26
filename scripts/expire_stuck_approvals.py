"""One-shot: mark every currently-approved proposal as 'expired'.

The execution worker (``scripts/execute_approved_proposals.py``) was
wired up after a backlog of approvals had already piled up — those stuck
proposals carry stale limit prices and should not be auto-submitted en
masse. This script clears the queue exactly once. From the next approval
onwards the worker will pick things up normally.

Defaults to a dry-run that lists what *would* change; pass ``--apply``
to commit the update.

Usage::

    python scripts/expire_stuck_approvals.py            # dry-run
    python scripts/expire_stuck_approvals.py --apply    # commit
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import select

from ai_agent.db.engine import get_session, init_schema
from ai_agent.db.models import Proposal, ProposalStatus

logger = logging.getLogger("expire_stuck_approvals")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the update (default: dry-run)")
    args = parser.parse_args(argv)

    init_schema()
    with get_session() as session:
        stuck = list(
            session.exec(select(Proposal).where(Proposal.status == ProposalStatus.approved)).all()
        )
        if not stuck:
            logger.info("No approved proposals found; nothing to do")
            return 0

        for p in stuck:
            logger.info(
                "  #%-4d %s %s qty=%s @ %s  decided=%s",
                p.id,
                p.side,
                p.symbol,
                p.quantity,
                p.limit_price,
                p.decided_at,
            )
        logger.info("Found %d approved proposal(s)", len(stuck))

        if not args.apply:
            logger.info("Dry-run: rerun with --apply to mark them expired")
            return 0

        for p in stuck:
            p.status = ProposalStatus.expired
            session.add(p)
        session.commit()
        logger.info("Marked %d proposal(s) as expired", len(stuck))
    return 0


if __name__ == "__main__":
    sys.exit(main())
