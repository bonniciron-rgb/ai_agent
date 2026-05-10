"""Idempotent order execution layer.

Wraps ``T212Client`` with:

* Deterministic idempotency keys derived from proposal metadata so that
  a retry of the same approval click cannot create a duplicate position.
* Pre-submission lookup: if the DB already has an order with the same key
  in a terminal-success state (submitted / filled), the existing order is
  returned without re-hitting T212.
* Failed / rejected orders are allowed a fresh retry — the same key is
  reused and the existing row is updated.
* The idempotency key is forwarded to T212 via the ``Idempotency-Key``
  HTTP header (best-effort; T212 may or may not honour it server-side).

Usage
-----
executor = OrderExecutor(t212_client=client)
order = executor.submit(proposal, session)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from ai_agent.broker.t212_client import T212Client
from ai_agent.db.models import Order, OrderStatus, OrderType, Proposal

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Statuses that indicate the order already completed successfully — no retry needed.
_SUCCESS_STATUSES = {OrderStatus.submitted, OrderStatus.filled, OrderStatus.partially_filled}

# Statuses that allow a fresh retry with the same idempotency key.
_RETRYABLE_STATUSES = {OrderStatus.rejected, OrderStatus.expired}


def make_idempotency_key(
    proposal_id: int,
    side: str,
    quantity: Decimal,
    decided_at: datetime,
) -> str:
    """Return a 32-char hex key that is stable across retries of the same approval.

    Formula: sha256(f"{proposal_id}:{side}:{quantity}:{decided_at_iso}")[:32]
    """
    decided_iso = decided_at.isoformat() if decided_at else "unknown"
    raw = f"{proposal_id}:{side}:{quantity}:{decided_iso}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class OrderExecutor:
    """Submit orders to T212 with idempotency guarantees.

    Parameters
    ----------
    t212_client:
        Authenticated ``T212Client`` instance.
    """

    def __init__(self, t212_client: T212Client) -> None:
        self._t212 = t212_client

    def submit_from_proposal(
        self,
        proposal: Proposal,
        session: Session,
    ) -> Order:
        """Submit (or retrieve) an order for *proposal*.

        The method is safe to call multiple times for the same proposal:
        duplicate submissions return the existing order without touching T212.

        Parameters
        ----------
        proposal:
            The approved ``Proposal`` ORM row.  Must have ``id`` and
            ``decided_at`` set.
        session:
            An active SQLModel session (caller owns commit/rollback).

        Returns
        -------
        The ``Order`` row, either retrieved from DB or newly created.
        """
        if proposal.id is None:
            raise ValueError("Proposal must be persisted before submitting an order")
        if proposal.decided_at is None:
            raise ValueError("Proposal.decided_at must be set before submitting an order")

        ikey = make_idempotency_key(
            proposal_id=proposal.id,
            side=str(proposal.side),
            quantity=proposal.quantity,
            decided_at=proposal.decided_at,
        )

        # --- Idempotency check ---
        existing = session.exec(select(Order).where(Order.idempotency_key == ikey)).first()

        if existing is not None:
            if existing.status in _SUCCESS_STATUSES:
                logger.info(
                    "Idempotency hit for key %s — returning existing order #%d (status=%s)",
                    ikey,
                    existing.id,
                    existing.status,
                )
                return existing
            # Retryable — fall through and re-submit, updating the existing row.
            logger.info(
                "Idempotency key %s found with retryable status %s — re-submitting",
                ikey,
                existing.status,
            )

        # --- Submit to T212 ---
        order_type = self._resolve_order_type(proposal)
        t212_response = self._place_order(proposal, ikey, order_type)

        now = datetime.now(UTC)

        if existing is not None:
            # Update existing failed/rejected row in-place.
            existing.broker_order_id = str(t212_response.id)
            existing.status = OrderStatus.submitted
            existing.submitted_at = now
            existing.raw_response = t212_response.model_dump_json()
            session.add(existing)
            return existing

        # Create a fresh Order row.
        order = Order(
            proposal_id=proposal.id,
            broker_order_id=str(t212_response.id),
            symbol=proposal.symbol,
            side=proposal.side,
            order_type=order_type,
            quantity=proposal.quantity,
            limit_price=proposal.limit_price,
            stop_price=proposal.stop_price,
            status=OrderStatus.submitted,
            submitted_at=now,
            idempotency_key=ikey,
            raw_response=t212_response.model_dump_json(),
        )
        session.add(order)
        return order

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_order_type(self, proposal: Proposal) -> OrderType:
        if proposal.stop_price is not None and proposal.limit_price is not None:
            return OrderType.stop_limit
        return OrderType.limit

    def _place_order(self, proposal: Proposal, ikey: str, order_type: OrderType):
        """Call T212 with the idempotency key injected as a request header."""
        # Temporarily patch the client's shared headers for this request.
        # We restore them afterwards to avoid leaking state.
        original_headers = dict(self._t212._headers)
        try:
            self._t212._headers["Idempotency-Key"] = ikey
            # Also update the underlying httpx client's headers.
            self._t212._http.headers["Idempotency-Key"] = ikey

            ticker = self._make_ticker(proposal.symbol)
            if order_type == OrderType.stop_limit:
                return self._t212.place_stop_limit_order(
                    ticker=ticker,
                    quantity=proposal.quantity,
                    limit_price=proposal.limit_price,
                    stop_price=proposal.stop_price,  # type: ignore[arg-type]
                )
            return self._t212.place_limit_order(
                ticker=ticker,
                quantity=proposal.quantity,
                limit_price=proposal.limit_price,
            )
        finally:
            # Restore original headers.
            self._t212._headers.clear()
            self._t212._headers.update(original_headers)
            # Restore httpx client headers (remove the idempotency key).
            self._t212._http.headers.pop("Idempotency-Key", None)

    @staticmethod
    def _make_ticker(symbol: str) -> str:
        """Convert bare symbol (e.g. 'AAPL') to T212 ticker ('AAPL_US_EQ').

        T212 uses ``{SYMBOL}_US_EQ`` for US equities.  This is a best-effort
        heuristic — the watchlist config can override tickers if needed.
        """
        if "_" in symbol:
            return symbol  # Already a full T212 ticker.
        return f"{symbol}_US_EQ"
