"""Submit approved proposals to the broker and record Order rows.

Called by the Telegram approval handler immediately after a user presses
"Approve" on a digest message.

T212 ticker convention
----------------------
T212 uses instrument tickers like ``AAPL_US_EQ`` for US equity.  The watchlist
stores plain symbols (``AAPL``).  We default to ``{symbol}_US_EQ`` for every
symbol; add a ``t212_ticker`` override to ``watchlist.yaml`` entries to handle
exceptions (e.g. ETFs or non-US instruments).

Error handling
--------------
If the T212 call raises, we write an ``Order`` row with ``status=rejected``
and ``raw_response`` containing the error text so the failure is auditable.
The Proposal status is NOT changed to ``executed`` on failure so it stays
``approved`` and can be retried or investigated.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import select

from ai_agent.db import engine as _engine
from ai_agent.db.models import Order, OrderSide, OrderStatus, OrderType, Proposal, ProposalStatus

logger = logging.getLogger(__name__)


def _t212_ticker(symbol: str, ticker_overrides: dict[str, str] | None = None) -> str:
    """Return the T212 instrument ticker for *symbol*.

    Uses *ticker_overrides* first (from the watchlist ``t212_ticker`` field),
    then falls back to ``{SYMBOL}_US_EQ``.
    """
    if ticker_overrides and symbol.upper() in ticker_overrides:
        return ticker_overrides[symbol.upper()]
    return f"{symbol.upper()}_US_EQ"


def submit_order(
    proposal_id: int,
    t212_client,
    *,
    ticker_overrides: dict[str, str] | None = None,
) -> Order:
    """Load an approved Proposal, submit a limit/stop-limit order to T212, persist the result.

    Parameters
    ----------
    proposal_id:
        DB primary key of the Proposal row (must have status ``approved``).
    t212_client:
        Live or fake T212Client instance.
    ticker_overrides:
        Optional ``{symbol: t212_ticker}`` mapping; falls back to ``{symbol}_US_EQ``.

    Returns
    -------
    Order
        The persisted Order row (status ``submitted`` on success, ``rejected`` on broker error).

    Raises
    ------
    ValueError
        If the proposal does not exist or is not in ``approved`` status.
    """
    with _engine.get_session() as session:
        proposal = session.get(Proposal, proposal_id)
        if proposal is None:
            raise ValueError(f"Proposal #{proposal_id} not found")
        if proposal.status != ProposalStatus.approved:
            raise ValueError(
                f"Proposal #{proposal_id} has status {proposal.status!r}, expected 'approved'"
            )

        ticker = _t212_ticker(proposal.symbol, ticker_overrides)
        quantity = proposal.quantity
        limit_price = proposal.limit_price
        stop_price = proposal.stop_price

    # Determine order type
    has_stop = stop_price is not None
    order_type = OrderType.stop_limit if has_stop else OrderType.limit

    broker_order_id: str | None = None
    order_status = OrderStatus.submitted
    raw_response: str | None = None

    try:
        if has_stop:
            resp = t212_client.place_stop_limit_order(
                ticker,
                quantity=quantity,
                limit_price=limit_price,
                stop_price=stop_price,
            )
        else:
            resp = t212_client.place_limit_order(
                ticker,
                quantity=quantity,
                limit_price=limit_price,
            )
        broker_order_id = str(resp.id)
        raw_response = json.dumps({"broker_id": resp.id, "status": resp.status})
        logger.info(
            "Order submitted: proposal=%d ticker=%s broker_id=%s",
            proposal_id,
            ticker,
            broker_order_id,
        )
    except Exception as exc:
        order_status = OrderStatus.rejected
        raw_response = str(exc)
        logger.warning(
            "Order submission failed for proposal #%d (%s): %s",
            proposal_id,
            ticker,
            exc,
        )

    now = datetime.now(UTC)

    with _engine.get_session() as session:
        order = Order(
            proposal_id=proposal_id,
            broker_order_id=broker_order_id,
            symbol=proposal.symbol,
            side=OrderSide(str(proposal.side)),
            order_type=order_type,
            quantity=Decimal(str(quantity)),
            limit_price=limit_price,
            stop_price=stop_price,
            status=order_status,
            submitted_at=now if order_status == OrderStatus.submitted else None,
            raw_response=raw_response,
        )
        session.add(order)

        # Reload proposal in this session to update it
        db_proposal = session.get(Proposal, proposal_id)
        if db_proposal is not None and order_status == OrderStatus.submitted:
            db_proposal.status = ProposalStatus.executed
        session.commit()
        session.refresh(order)

    return order


def submit_approved_proposals(
    t212_client,
    *,
    ticker_overrides: dict[str, str] | None = None,
) -> list[Order]:
    """Find all ``approved`` proposals and submit them.

    Used by a cron or webhook to drain any proposals approved outside the
    normal real-time flow (e.g. restarts, batch approvals).
    """
    with _engine.get_session() as session:
        approved_ids = list(
            session.exec(
                select(Proposal.id).where(Proposal.status == ProposalStatus.approved)
            ).all()
        )

    orders: list[Order] = []
    for pid in approved_ids:
        try:
            orders.append(submit_order(pid, t212_client, ticker_overrides=ticker_overrides))
        except Exception as exc:
            logger.warning("Failed to submit order for proposal #%d: %s", pid, exc)

    return orders
