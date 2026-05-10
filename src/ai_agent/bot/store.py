"""DecisionStore backed by the SQLModel database.

Used by BotHandlers to record approval/rejection decisions.
Implements the DecisionStore protocol from handlers.py.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel import select

from ai_agent.db.engine import get_session
from ai_agent.db.models import Proposal, ProposalStatus, ShadowPosition

logger = logging.getLogger(__name__)

_ACTION_TO_STATUS = {
    "approve": ProposalStatus.approved,
    "reject": ProposalStatus.rejected,
    "defer": ProposalStatus.deferred,
    "edit": ProposalStatus.proposed,  # stays proposed, awaiting edit reply
}

# Map proposal action → shadow decision string
_ACTION_TO_SHADOW = {
    "approve": "approved",
    "reject": "rejected",
    "edit": "edited",
    "defer": None,  # deferral doesn't close the shadow
}


class DbDecisionStore:
    """Writes decisions to the Postgres/SQLite proposals table."""

    def record_decision(self, proposal_id: int, action: str, decided_by: str) -> None:
        if proposal_id < 0:
            # Special sentinel (e.g. halt) — no DB row to update
            logger.info("System action %r recorded (no DB row)", action)
            return
        status = _ACTION_TO_STATUS.get(action)
        if status is None:
            logger.warning("Unknown action %r for proposal #%d", action, proposal_id)
            return
        with get_session() as session:
            proposal = session.get(Proposal, proposal_id)
            if proposal is None:
                logger.warning("Proposal #%d not found", proposal_id)
                return
            proposal.status = status
            proposal.decided_at = datetime.now(UTC)
            proposal.decided_by = decided_by
            session.add(proposal)

            # Flip the shadow position decision
            shadow_decision = _ACTION_TO_SHADOW.get(action)
            if shadow_decision is not None:
                shadow_rows = session.exec(
                    select(ShadowPosition).where(
                        ShadowPosition.proposal_id == proposal_id,
                        ShadowPosition.decision.is_(None),  # type: ignore[union-attr]
                    )
                ).all()
                for shadow in shadow_rows:
                    shadow.decision = shadow_decision
                    session.add(shadow)

            session.commit()
            logger.info("Proposal #%d → %s by %s", proposal_id, status, decided_by)

    def get_proposal_symbol(self, proposal_id: int) -> str | None:
        with get_session() as session:
            proposal = session.get(Proposal, proposal_id)
            return proposal.symbol if proposal else None
