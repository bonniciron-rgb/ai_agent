"""Drain the queue of approved trade proposals and submit them to T212.

This module is invoked frequently (e.g. every 5 minutes) by a GitHub
Actions cron and by the ``scripts/execute_approved_proposals.py`` entry
point. It is the missing link between the user tapping *Approve* in the
Telegram bot / web dashboard (which only flips a DB status to
``approved``) and an actual order at the broker — without this worker,
approvals never reach Trading 212.

Each candidate proposal is submitted via ``OrderExecutor`` in its own
transaction so a failure on one proposal cannot roll back the success of
another. Idempotency keys inside ``OrderExecutor`` mean re-running this
worker over the same approved proposal will not create duplicate orders.
A T212 / network failure leaves the proposal in ``approved`` so the next
run retries it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from sqlmodel import select

from ai_agent.broker.order_executor import OrderExecutor
from ai_agent.broker.t212_client import T212Client
from ai_agent.db.engine import get_session, init_schema
from ai_agent.db.models import Proposal, ProposalStatus
from ai_agent.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_MAX_PER_RUN = int(os.environ.get("EXECUTE_MAX_PER_RUN", "20"))


def _fetch_approved_ids(*, limit: int) -> list[int]:
    """Return the oldest *limit* approved-proposal IDs, snapshotted out of the session."""
    with get_session() as session:
        stmt = (
            select(Proposal.id)
            .where(Proposal.status == ProposalStatus.approved)
            .order_by(Proposal.decided_at)  # type: ignore[arg-type]
            .limit(limit)
        )
        return [pid for pid in session.exec(stmt).all() if pid is not None]


def run(
    *,
    dry_run: bool = False,
    max_per_run: int = DEFAULT_MAX_PER_RUN,
    t212_client: Any | None = None,
    notify: bool = True,
) -> dict[str, int]:
    """Drain the approved-proposal queue once.

    Returns a counts dict ``{"executed": N, "failed": N, "dry_run": N}``.

    Parameters
    ----------
    dry_run:
        If True, log what would be submitted but never call T212 and never
        mutate proposal status.
    max_per_run:
        Cap on how many proposals one invocation will try (safety net
        against a runaway proposer flooding the broker).
    t212_client:
        Optional T212Client (or fake) for tests. Defaults to a real client
        built from settings.
    notify:
        If True, send a Telegram summary when at least one proposal was
        touched. Tests pass False to skip the network call.
    """
    init_schema()
    settings = get_settings()
    counts = {"executed": 0, "failed": 0, "dry_run": 0}
    notes: list[str] = []

    candidate_ids = _fetch_approved_ids(limit=max_per_run)
    if not candidate_ids:
        logger.info("No approved proposals to submit")
        return counts

    if t212_client is None:
        t212_client = T212Client(
            api_key=settings.t212_api_key.get_secret_value(),
            api_secret=settings.t212_api_secret.get_secret_value(),
            base_url=settings.t212_base_url,
        )
    executor = OrderExecutor(t212_client=t212_client)

    for pid in candidate_ids:
        # Each proposal gets its own session so per-proposal commits are
        # durable and a failure on one cannot poison the next.
        with get_session() as session:
            proposal = session.get(Proposal, pid)
            if proposal is None or proposal.status != ProposalStatus.approved:
                # Status flipped by a concurrent process (or proposal deleted) — skip.
                logger.info(
                    "Skip #%s: status is %s",
                    pid,
                    proposal.status if proposal else "missing",
                )
                continue
            tag = f"#{pid} {proposal.side} {proposal.symbol} qty={proposal.quantity}"

            if dry_run:
                logger.info("[dry_run] Would submit %s", tag)
                counts["dry_run"] += 1
                continue

            try:
                order = executor.submit_from_proposal(proposal, session)
                proposal.status = ProposalStatus.executed
                session.add(proposal)
                session.commit()
            except Exception as exc:
                session.rollback()
                logger.exception("Failed to submit %s", tag)
                counts["failed"] += 1
                notes.append(f"❌ {tag} failed: {exc}")
                continue

            logger.info(
                "Submitted %s → order #%s (broker %s)",
                tag,
                order.id,
                order.broker_order_id,
            )
            counts["executed"] += 1
            notes.append(f"✅ {tag} → order #{order.id}")

    if notify and not dry_run and notes:
        try:
            asyncio.run(_send_telegram_summary(notes, settings))
        except Exception:
            logger.exception("Telegram summary failed (orders themselves are still submitted)")

    return counts


async def _send_telegram_summary(notes: list[str], settings) -> None:
    """Best-effort Telegram digest of the per-proposal outcomes."""
    try:
        from telegram import Bot
    except ImportError:
        return
    token = settings.telegram_bot_token.get_secret_value()
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        return
    body = "📤 Approved proposals processed:\n" + "\n".join(notes)
    async with Bot(token=token) as bot:
        await bot.send_message(chat_id=chat_id, text=body[:4000])


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Log without submitting to T212")
    parser.add_argument(
        "--max",
        type=int,
        default=DEFAULT_MAX_PER_RUN,
        help=f"Max proposals per run (default {DEFAULT_MAX_PER_RUN})",
    )
    args = parser.parse_args(argv)
    counts = run(dry_run=args.dry_run, max_per_run=args.max)
    logger.info("Done: %s", counts)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    sys.exit(main())
