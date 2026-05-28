"""Tests for idempotent order execution via OrderExecutor."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from ai_agent.broker.order_executor import OrderExecutor, make_idempotency_key
from ai_agent.broker.t212_client import T212Client
from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import Order, OrderSide, OrderStatus, OrderType, Proposal, ProposalStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> Engine:
    eng = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(eng)
    return eng


_DECIDED_AT = datetime(2025, 1, 10, 14, 30, 0, tzinfo=UTC)


def _save_proposal(session: Session) -> Proposal:
    p = Proposal(
        expires_at=datetime(2025, 1, 11, 14, 30, 0, tzinfo=UTC),
        symbol="AAPL",
        side=OrderSide.buy,
        quantity=Decimal("5"),
        limit_price=Decimal("175.00"),
        rationale="test",
        confidence="high",
        status=ProposalStatus.approved,
        decided_at=_DECIDED_AT,
        decided_by="@alice",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _counting_t212_client(order_id: int = 42) -> tuple[T212Client, list[int]]:
    """Return (client, call_log) where call_log grows by 1 on each T212 request."""
    call_log: list[int] = []

    payload = {
        "id": order_id,
        "ticker": "AAPL_US_EQ",
        "quantity": "5",
        "status": "PENDING",
        "type": "LIMIT",
        "limitPrice": "175.00",
        "filledQuantity": "0",
        "creationTime": "2025-01-10T14:30:00.000Z",
        "timeValidity": "GTC",
    }

    class _Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            call_log.append(1)
            return httpx.Response(
                200,
                text=json.dumps(payload),
                headers={"content-type": "application/json"},
            )

    http = httpx.Client(transport=_Transport(), base_url="https://demo.trading212.com")
    return T212Client(api_key="test-key", http_client=http), call_log


# ---------------------------------------------------------------------------
# Unit tests — idempotency key generation
# ---------------------------------------------------------------------------


def test_idempotency_key_is_deterministic() -> None:
    """Same inputs must always produce the same 32-char hex key."""
    key1 = make_idempotency_key(1, "buy", Decimal("5"), _DECIDED_AT)
    key2 = make_idempotency_key(1, "buy", Decimal("5"), _DECIDED_AT)
    assert key1 == key2
    assert len(key1) == 32


def test_idempotency_key_differs_on_different_proposal() -> None:
    key1 = make_idempotency_key(1, "buy", Decimal("5"), _DECIDED_AT)
    key2 = make_idempotency_key(2, "buy", Decimal("5"), _DECIDED_AT)
    assert key1 != key2


def test_idempotency_key_differs_on_different_decided_at() -> None:
    dt2 = datetime(2025, 1, 10, 14, 31, 0, tzinfo=UTC)
    key1 = make_idempotency_key(1, "buy", Decimal("5"), _DECIDED_AT)
    key2 = make_idempotency_key(1, "buy", Decimal("5"), dt2)
    assert key1 != key2


# ---------------------------------------------------------------------------
# Unit tests — submit_from_proposal
# ---------------------------------------------------------------------------


def test_submit_creates_order(engine: Engine) -> None:
    """First submission creates an Order row with status=submitted."""
    client, call_log = _counting_t212_client(order_id=100)
    executor = OrderExecutor(t212_client=client)

    with Session(engine) as session:
        proposal = _save_proposal(session)
        order = executor.submit_from_proposal(proposal, session)
        session.commit()
        order_id = order.id
        ikey = order.idempotency_key

    assert order_id is not None
    assert len(call_log) == 1  # T212 called exactly once

    # Verify order was persisted correctly
    with Session(engine) as session:
        stored = session.get(Order, order_id)
        assert stored is not None
        assert stored.status == OrderStatus.submitted
        assert stored.broker_order_id == "100"
        assert ikey is not None
        assert len(ikey) == 32


def test_submit_twice_returns_existing_order_without_t212_call(engine: Engine) -> None:
    """Re-submitting with same approval data returns the existing order (no T212 call)."""
    client, call_log = _counting_t212_client(order_id=999)
    executor = OrderExecutor(t212_client=client)

    with Session(engine) as session:
        proposal = _save_proposal(session)
        proposal_id = proposal.id

        # First submission
        order_a = executor.submit_from_proposal(proposal, session)
        session.commit()
        order_a_id = order_a.id
        order_a_ikey = order_a.idempotency_key

    assert len(call_log) == 1  # T212 called once

    # Second submission — simulates a retry after a network timeout
    with Session(engine) as session:
        fresh_proposal = session.get(Proposal, proposal_id)
        assert fresh_proposal is not None

        order_b = executor.submit_from_proposal(fresh_proposal, session)
        order_b_id = order_b.id
        order_b_ikey = order_b.idempotency_key

    assert len(call_log) == 1  # T212 NOT called again
    assert order_a_id == order_b_id  # same row returned
    assert order_a_ikey == order_b_ikey  # same key


def test_submit_after_rejected_retries_t212(engine: Engine) -> None:
    """Re-submitting after a rejected order status DOES make a fresh T212 call."""
    client, call_log = _counting_t212_client(order_id=77)
    executor = OrderExecutor(t212_client=client)

    with Session(engine) as session:
        proposal = _save_proposal(session)
        proposal_id = proposal.id

        # Compute the expected ikey
        ikey = make_idempotency_key(
            proposal.id,  # type: ignore[arg-type]
            str(proposal.side),
            proposal.quantity,
            proposal.decided_at,  # type: ignore[arg-type]
        )

        # Manually plant a rejected order with this key
        rejected_order = Order(
            proposal_id=proposal.id,
            broker_order_id="old-id",
            symbol="AAPL",
            side=OrderSide.buy,
            order_type=OrderType.limit,
            quantity=Decimal("5"),
            limit_price=Decimal("175.00"),
            status=OrderStatus.rejected,
            idempotency_key=ikey,
        )
        session.add(rejected_order)
        session.commit()

    # Now submit — should retry because status is 'rejected'
    with Session(engine) as session:
        proposal = session.get(Proposal, proposal_id)
        assert proposal is not None
        order = executor.submit_from_proposal(proposal, session)
        session.commit()
        updated_status = order.status
        updated_broker_id = order.broker_order_id

    assert len(call_log) == 1  # T212 was called (retry allowed)
    assert updated_status == OrderStatus.submitted
    assert updated_broker_id == "77"


# ---------------------------------------------------------------------------
# Sell-side direction encoding
# ---------------------------------------------------------------------------


def _capturing_t212_client() -> tuple[T212Client, list[dict]]:
    """Return (client, captured_payloads) — records each request body it sees."""
    captured: list[dict] = []
    payload = {
        "id": 555,
        "ticker": "CSCO_US_EQ",
        "quantity": "-0.99344498",
        "status": "PENDING",
        "type": "LIMIT",
        "limitPrice": "66.00",
        "filledQuantity": "0",
        "creationTime": "2026-05-26T14:30:00.000Z",
        "timeValidity": "GTC",
    }

    class _Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                captured.append(json.loads(request.content.decode()))
            return httpx.Response(
                200,
                text=json.dumps(payload),
                headers={"content-type": "application/json"},
            )

    http = httpx.Client(transport=_Transport(), base_url="https://demo.trading212.com")
    return T212Client(api_key="test", http_client=http), captured


def test_sell_proposal_submits_negative_quantity(engine: Engine) -> None:
    """T212 encodes order direction as quantity sign — sells must go negative.

    Regression test for the bug where the worker shipped sells with positive
    quantities and T212 returned 400 'Invalid payload' on every approved
    SELL proposal (CSCO/IBM/QCOM in the first live run of PR #92).
    """
    client, captured = _capturing_t212_client()
    executor = OrderExecutor(t212_client=client)

    with Session(engine) as session:
        proposal = Proposal(
            expires_at=datetime(2026, 5, 27, 14, 30, tzinfo=UTC),
            symbol="CSCO",
            side=OrderSide.sell,
            quantity=Decimal("0.99344498"),
            limit_price=Decimal("66.00"),
            rationale="exit",
            confidence="high",
            status=ProposalStatus.approved,
            decided_at=_DECIDED_AT,
            decided_by="@alice",
        )
        session.add(proposal)
        session.commit()
        session.refresh(proposal)
        executor.submit_from_proposal(proposal, session)
        session.commit()

    assert len(captured) == 1
    body = captured[0]
    # Quantity must be serialised negative; sign tells T212 it's a sell.
    assert Decimal(str(body["quantity"])) == Decimal("-0.99344498")
    assert body["ticker"] == "CSCO_US_EQ"


def test_buy_proposal_still_submits_positive_quantity(engine: Engine) -> None:
    """Belt-and-braces: the sign flip must not regress the buy path."""
    client, captured = _capturing_t212_client()
    executor = OrderExecutor(t212_client=client)

    with Session(engine) as session:
        proposal = _save_proposal(session)  # buy AAPL qty=5
        executor.submit_from_proposal(proposal, session)
        session.commit()

    assert len(captured) == 1
    assert Decimal(str(captured[0]["quantity"])) == Decimal("5")
