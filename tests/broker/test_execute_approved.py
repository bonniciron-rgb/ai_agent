"""Tests for the approved-proposal execution worker.

Covers the missing link wired in by Batch 51: approval handlers only flip
the DB status to ``approved``, so without this worker draining the queue
and submitting via OrderExecutor no order ever reaches T212.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from ai_agent.broker.execute_approved import run
from ai_agent.broker.t212_client import T212Client
from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import Order, OrderSide, Proposal, ProposalStatus

_DECIDED_AT = datetime(2026, 5, 25, 14, 30, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _db(monkeypatch) -> Engine:
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)
    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)
    return engine


def _seed_approved(
    session: Session,
    *,
    symbol: str = "AAPL",
    quantity: str = "5",
    side: OrderSide = OrderSide.buy,
) -> Proposal:
    p = Proposal(
        expires_at=datetime(2026, 5, 26, tzinfo=UTC),
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
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


def _ok_t212(order_id: int = 100) -> T212Client:
    """Fake T212 that returns a successful order payload."""
    payload = {
        "id": order_id,
        "ticker": "AAPL_US_EQ",
        "quantity": "5",
        "status": "PENDING",
        "type": "LIMIT",
        "limitPrice": "175.00",
        "filledQuantity": "0",
        "creationTime": "2026-05-25T14:30:00.000Z",
        "timeValidity": "GTC",
    }

    class _OK(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text=json.dumps(payload),
                headers={"content-type": "application/json"},
            )

    http = httpx.Client(transport=_OK(), base_url="https://demo.trading212.com")
    return T212Client(api_key="test", http_client=http)


def _broken_t212() -> T212Client:
    """Fake T212 that returns HTTP 500 — exercises the failure path."""

    class _Boom(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500,
                text='{"error":"broker meltdown"}',
                headers={"content-type": "application/json"},
            )

    http = httpx.Client(transport=_Boom(), base_url="https://demo.trading212.com")
    return T212Client(api_key="test", http_client=http)


def test_no_approved_returns_zero_counts() -> None:
    counts = run(t212_client=_ok_t212(), notify=False)
    assert counts == {"executed": 0, "failed": 0, "dry_run": 0}


def test_submits_approved_proposal(_db: Engine) -> None:
    with Session(_db) as session:
        pid = _seed_approved(session).id

    counts = run(t212_client=_ok_t212(), notify=False)
    assert counts == {"executed": 1, "failed": 0, "dry_run": 0}

    with Session(_db) as session:
        p = session.get(Proposal, pid)
        assert p is not None
        assert p.status == ProposalStatus.executed
        orders = list(session.exec(select(Order)).all())
        assert len(orders) == 1
        assert orders[0].proposal_id == pid
        assert orders[0].broker_order_id == "100"


def test_dry_run_does_not_call_t212_or_mutate(_db: Engine) -> None:
    with Session(_db) as session:
        pid = _seed_approved(session).id

    class _Forbidden(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise AssertionError("T212 must not be called in dry-run mode")

    http = httpx.Client(transport=_Forbidden(), base_url="https://demo.trading212.com")
    client = T212Client(api_key="test", http_client=http)

    counts = run(t212_client=client, dry_run=True, notify=False)
    assert counts == {"executed": 0, "failed": 0, "dry_run": 1}

    with Session(_db) as session:
        p = session.get(Proposal, pid)
        # Proposal still approved → next worker run will pick it up.
        assert p.status == ProposalStatus.approved
        assert list(session.exec(select(Order)).all()) == []


def test_failure_leaves_proposal_for_retry(_db: Engine) -> None:
    with Session(_db) as session:
        pid = _seed_approved(session).id

    counts = run(t212_client=_broken_t212(), notify=False)
    assert counts == {"executed": 0, "failed": 1, "dry_run": 0}

    with Session(_db) as session:
        p = session.get(Proposal, pid)
        # Critical: a transient broker failure must not lose the approval.
        assert p.status == ProposalStatus.approved


def test_respects_max_per_run(_db: Engine) -> None:
    with Session(_db) as session:
        for i in range(5):
            _seed_approved(session, symbol=f"SYM{i}")

    counts = run(t212_client=_ok_t212(), max_per_run=2, notify=False)
    assert counts["executed"] == 2

    with Session(_db) as session:
        executed = list(
            session.exec(select(Proposal).where(Proposal.status == ProposalStatus.executed)).all()
        )
        approved = list(
            session.exec(select(Proposal).where(Proposal.status == ProposalStatus.approved)).all()
        )
        assert len(executed) == 2
        assert len(approved) == 3
