"""Tests for the order executor — approved proposal → T212 submission → Order DB row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import Order, OrderStatus, Proposal, ProposalStatus
from ai_agent.loop.order_executor import _t212_ticker, submit_approved_proposals, submit_order

# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)

    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)

    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def _get_session(engine_arg=None) -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(eng_mod, "get_session", _get_session)
    return engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proposal(
    session: Session,
    *,
    symbol: str = "AAPL",
    side: str = "buy",
    quantity: Decimal = Decimal("10"),
    limit_price: Decimal = Decimal("150"),
    stop_price: Decimal | None = None,
    status: ProposalStatus = ProposalStatus.approved,
) -> Proposal:
    p = Proposal(
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        rationale="test rationale",
        confidence="medium",
        status=status,
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


class FakeT212:
    """Returns a stub OrderResponse; records calls for assertion."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.limit_calls: list[dict] = []
        self.stop_limit_calls: list[dict] = []
        self._next_id = 1001

    def place_limit_order(self, ticker, *, quantity, limit_price, **kwargs):
        if self._fail:
            raise RuntimeError("T212 unavailable")
        self.limit_calls.append({"ticker": ticker, "qty": quantity, "price": limit_price})
        resp = SimpleNamespace(id=self._next_id, status="OPEN")
        self._next_id += 1
        return resp

    def place_stop_limit_order(self, ticker, *, quantity, limit_price, stop_price, **kwargs):
        if self._fail:
            raise RuntimeError("T212 unavailable")
        self.stop_limit_calls.append(
            {"ticker": ticker, "qty": quantity, "limit": limit_price, "stop": stop_price}
        )
        resp = SimpleNamespace(id=self._next_id, status="OPEN")
        self._next_id += 1
        return resp


# ---------------------------------------------------------------------------
# _t212_ticker helper
# ---------------------------------------------------------------------------


def test_ticker_default_suffix() -> None:
    assert _t212_ticker("AAPL") == "AAPL_US_EQ"


def test_ticker_uppercase() -> None:
    assert _t212_ticker("msft") == "MSFT_US_EQ"


def test_ticker_override_used() -> None:
    overrides = {"AAPL": "AAPL_US_EQ_SPECIAL"}
    assert _t212_ticker("AAPL", overrides) == "AAPL_US_EQ_SPECIAL"


def test_ticker_override_case_insensitive() -> None:
    overrides = {"AAPL": "AAPL_US_EQ_SPECIAL"}
    assert _t212_ticker("aapl", overrides) == "AAPL_US_EQ_SPECIAL"


# ---------------------------------------------------------------------------
# submit_order — happy paths
# ---------------------------------------------------------------------------


def test_submit_limit_order_creates_db_row(_db) -> None:
    with Session(_db) as session:
        p = _make_proposal(session)
        pid = p.id

    client = FakeT212()
    order = submit_order(pid, client)

    assert order.status == OrderStatus.submitted
    assert order.broker_order_id is not None
    assert order.symbol == "AAPL"
    assert order.submitted_at is not None

    with Session(_db) as session:
        rows = session.exec(select(Order)).all()
        assert len(rows) == 1
        assert rows[0].status == OrderStatus.submitted


def test_submit_limit_order_marks_proposal_executed(_db) -> None:
    with Session(_db) as session:
        p = _make_proposal(session)
        pid = p.id

    submit_order(pid, FakeT212())

    with Session(_db) as session:
        prop = session.get(Proposal, pid)
        assert prop.status == ProposalStatus.executed


def test_submit_limit_order_calls_limit_endpoint(_db) -> None:
    with Session(_db) as session:
        p = _make_proposal(session, stop_price=None)
        pid = p.id

    client = FakeT212()
    submit_order(pid, client)

    assert len(client.limit_calls) == 1
    assert len(client.stop_limit_calls) == 0
    assert client.limit_calls[0]["ticker"] == "AAPL_US_EQ"


def test_submit_stop_limit_order_calls_stop_limit_endpoint(_db) -> None:
    with Session(_db) as session:
        p = _make_proposal(session, stop_price=Decimal("145"))
        pid = p.id

    client = FakeT212()
    submit_order(pid, client)

    assert len(client.stop_limit_calls) == 1
    assert len(client.limit_calls) == 0
    assert client.stop_limit_calls[0]["stop"] == Decimal("145")


def test_submit_order_uses_ticker_override(_db) -> None:
    with Session(_db) as session:
        p = _make_proposal(session)
        pid = p.id

    client = FakeT212()
    submit_order(pid, client, ticker_overrides={"AAPL": "AAPL_US_EQ_CUSTOM"})

    assert client.limit_calls[0]["ticker"] == "AAPL_US_EQ_CUSTOM"


# ---------------------------------------------------------------------------
# submit_order — error paths
# ---------------------------------------------------------------------------


def test_proposal_not_found_raises(_db) -> None:
    with pytest.raises(ValueError, match="not found"):
        submit_order(9999, FakeT212())


def test_proposal_not_approved_raises(_db) -> None:
    with Session(_db) as session:
        p = _make_proposal(session, status=ProposalStatus.proposed)
        pid = p.id

    with pytest.raises(ValueError, match="approved"):
        submit_order(pid, FakeT212())


def test_t212_error_creates_rejected_order(_db) -> None:
    with Session(_db) as session:
        p = _make_proposal(session)
        pid = p.id

    order = submit_order(pid, FakeT212(fail=True))

    assert order.status == OrderStatus.rejected
    assert "T212 unavailable" in (order.raw_response or "")

    # Proposal should NOT be marked executed when submission failed
    with Session(_db) as session:
        prop = session.get(Proposal, pid)
        assert prop.status == ProposalStatus.approved


def test_t212_error_does_not_raise(_db) -> None:
    """Broker errors are caught — submit_order returns an Order, not an exception."""
    with Session(_db) as session:
        p = _make_proposal(session)
        pid = p.id

    order = submit_order(pid, FakeT212(fail=True))
    assert order is not None


# ---------------------------------------------------------------------------
# submit_approved_proposals — batch drain
# ---------------------------------------------------------------------------


def test_submit_approved_proposals_drains_all(_db) -> None:
    with Session(_db) as session:
        _make_proposal(session, symbol="AAPL")
        _make_proposal(session, symbol="MSFT")

    client = FakeT212()
    orders = submit_approved_proposals(client)

    assert len(orders) == 2
    symbols = {o.symbol for o in orders}
    assert symbols == {"AAPL", "MSFT"}


def test_submit_approved_proposals_skips_non_approved(_db) -> None:
    with Session(_db) as session:
        _make_proposal(session, symbol="AAPL", status=ProposalStatus.proposed)
        _make_proposal(session, symbol="MSFT", status=ProposalStatus.approved)

    client = FakeT212()
    orders = submit_approved_proposals(client)

    assert len(orders) == 1
    assert orders[0].symbol == "MSFT"


def test_submit_approved_proposals_continues_on_error(_db) -> None:
    """If one submission fails, the rest still execute."""
    with Session(_db) as session:
        _make_proposal(session, symbol="AAPL")
        _make_proposal(session, symbol="MSFT")

    call_count = 0

    class SelectiveFail:
        def place_limit_order(self, ticker, **kwargs):
            nonlocal call_count
            call_count += 1
            if "AAPL" in ticker:
                raise RuntimeError("rate limited")
            return SimpleNamespace(id=1, status="OPEN")

        def place_stop_limit_order(self, ticker, **kwargs):
            return self.place_limit_order(ticker, **kwargs)

    orders = submit_approved_proposals(SelectiveFail())
    assert len(orders) == 2
    statuses = {o.symbol: o.status for o in orders}
    assert statuses["AAPL"] == OrderStatus.rejected
    assert statuses["MSFT"] == OrderStatus.submitted
