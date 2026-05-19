"""Tests for the nightly reconciliation logic."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from ai_agent.broker.models import OpenPosition, OrderResponse
from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Reconciliation,
)
from ai_agent.reconciliation import (
    compare_orders,
    compare_positions,
    run_reconciliation,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> Engine:
    eng = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(eng)
    return eng


def _make_t212_position(ticker: str, quantity: str) -> OpenPosition:
    return OpenPosition(
        ticker=ticker,
        quantity=Decimal(quantity),
        averagePrice=Decimal("100"),
        currentPrice=Decimal("105"),
    )


def _make_t212_order(order_id: int, ticker: str, status: str = "PENDING") -> OrderResponse:
    return OrderResponse(
        id=order_id,
        ticker=ticker,
        quantity=Decimal("5"),
        status=status,
        type="LIMIT",
        limitPrice=Decimal("175"),
        filledQuantity=Decimal("0"),
        timeValidity="GTC",
        creationTime="2025-01-10T14:30:00.000Z",
    )


def _make_db_position(session: Session, symbol: str, quantity: str) -> Position:
    pos = Position(
        symbol=symbol,
        quantity=Decimal(quantity),
        avg_price=Decimal("100"),
    )
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return pos


def _make_db_order(
    session: Session,
    symbol: str,
    broker_order_id: str | None,
    status: OrderStatus = OrderStatus.submitted,
) -> Order:
    order = Order(
        symbol=symbol,
        side=OrderSide.buy,
        order_type=OrderType.limit,
        quantity=Decimal("5"),
        limit_price=Decimal("175"),
        status=status,
        submitted_at=datetime.now(UTC),
        broker_order_id=broker_order_id,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


# ---------------------------------------------------------------------------
# Unit tests — compare_positions
# ---------------------------------------------------------------------------


def test_compare_positions_no_drift() -> None:
    """Matching positions should produce no drifts."""
    db_positions = [
        Position(symbol="AAPL", quantity=Decimal("5"), avg_price=Decimal("170")),
        Position(symbol="MSFT", quantity=Decimal("10"), avg_price=Decimal("390")),
    ]
    t212_positions = [
        _make_t212_position("AAPL_US_EQ", "5"),
        _make_t212_position("MSFT_US_EQ", "10"),
    ]
    drifts = compare_positions(db_positions, t212_positions)
    assert drifts == []


def test_compare_positions_missing_in_db() -> None:
    """Symbol in T212 but not DB should be flagged."""
    db_positions: list[Position] = []
    t212_positions = [_make_t212_position("AAPL_US_EQ", "5")]
    drifts = compare_positions(db_positions, t212_positions)
    assert len(drifts) == 1
    assert drifts[0]["type"] == "position_missing_in_db"
    assert drifts[0]["symbol"] == "AAPL"


def test_compare_positions_missing_in_t212() -> None:
    """Symbol in DB but not T212 should be flagged."""
    db_positions = [Position(symbol="AAPL", quantity=Decimal("5"), avg_price=Decimal("170"))]
    t212_positions: list = []
    drifts = compare_positions(db_positions, t212_positions)
    assert len(drifts) == 1
    assert drifts[0]["type"] == "position_missing_in_t212"
    assert drifts[0]["symbol"] == "AAPL"


def test_compare_positions_quantity_mismatch() -> None:
    """Material quantity difference should be flagged."""
    db_positions = [Position(symbol="AAPL", quantity=Decimal("5"), avg_price=Decimal("170"))]
    t212_positions = [_make_t212_position("AAPL_US_EQ", "10")]  # big difference
    drifts = compare_positions(db_positions, t212_positions)
    assert len(drifts) == 1
    assert drifts[0]["type"] == "position_quantity_mismatch"


def test_compare_positions_trivial_quantity_difference_ignored() -> None:
    """Sub-threshold quantity difference (< 1 share AND < 0.1%) should not be flagged."""
    db_positions = [Position(symbol="AAPL", quantity=Decimal("100.00"), avg_price=Decimal("170"))]
    t212_positions = [_make_t212_position("AAPL_US_EQ", "100.05")]  # 0.05 shares = 0.05%
    drifts = compare_positions(db_positions, t212_positions)
    assert drifts == []


# ---------------------------------------------------------------------------
# Unit tests — compare_orders
# ---------------------------------------------------------------------------


def test_compare_orders_no_drift() -> None:
    """Matching orders should produce no drifts."""
    db_orders = [
        Order(
            symbol="AAPL",
            side=OrderSide.buy,
            order_type=OrderType.limit,
            quantity=Decimal("5"),
            status=OrderStatus.submitted,
            broker_order_id="42",
        )
    ]
    t212_orders = [_make_t212_order(42, "AAPL_US_EQ", "PENDING")]
    drifts = compare_orders(db_orders, t212_orders)
    assert drifts == []


def test_compare_orders_filled_at_t212_but_submitted_in_db() -> None:
    """T212-filled order that's still submitted in DB should be flagged."""
    db_orders = [
        Order(
            symbol="AAPL",
            side=OrderSide.buy,
            order_type=OrderType.limit,
            quantity=Decimal("5"),
            status=OrderStatus.submitted,
            broker_order_id="42",
        )
    ]
    t212_orders = [_make_t212_order(42, "AAPL_US_EQ", "FILLED")]
    drifts = compare_orders(db_orders, t212_orders)
    assert len(drifts) == 1
    assert drifts[0]["type"] == "order_filled_at_t212_but_db_submitted"


def test_compare_orders_db_submitted_not_at_t212() -> None:
    """DB-submitted order not found at T212 should be flagged."""
    db_orders = [
        Order(
            symbol="AAPL",
            side=OrderSide.buy,
            order_type=OrderType.limit,
            quantity=Decimal("5"),
            status=OrderStatus.submitted,
            broker_order_id="99",
        )
    ]
    t212_orders: list = []  # T212 knows nothing about order 99
    drifts = compare_orders(db_orders, t212_orders)
    assert len(drifts) == 1
    assert drifts[0]["type"] == "order_submitted_in_db_not_found_at_t212"


def test_compare_orders_t212_order_not_in_db() -> None:
    """T212 has an order that our DB doesn't know about."""
    db_orders: list[Order] = []
    t212_orders = [_make_t212_order(100, "MSFT_US_EQ", "PENDING")]
    drifts = compare_orders(db_orders, t212_orders)
    assert len(drifts) == 1
    assert drifts[0]["type"] == "order_in_t212_not_in_db"


# ---------------------------------------------------------------------------
# Integration tests — run_reconciliation end-to-end
# ---------------------------------------------------------------------------


def _make_mock_t212(positions=None, orders=None):
    """Build a mock T212Client with configurable responses."""
    mock = MagicMock()
    mock.get_positions.return_value = positions or []
    mock.get_orders.return_value = orders or []
    return mock


def test_reconciliation_ok_scenario(engine: Engine) -> None:
    """All DB positions and orders match T212 — status should be 'ok'."""
    with Session(engine) as session:
        _make_db_position(session, "AAPL", "5")
        _make_db_order(session, "AAPL", broker_order_id="42")

    t212_client = _make_mock_t212(
        positions=[_make_t212_position("AAPL_US_EQ", "5")],
        orders=[_make_t212_order(42, "AAPL_US_EQ", "PENDING")],
    )

    row = run_reconciliation(t212_client=t212_client, engine=engine)

    assert row.status == "ok"
    assert row.position_drifts == 0
    assert row.order_drifts == 0
    assert row.id is not None

    # Verify it was persisted to DB
    with Session(engine) as session:
        stored = session.get(Reconciliation, row.id)
    assert stored is not None
    assert stored.status == "ok"


def test_reconciliation_drift_scenario(engine: Engine) -> None:
    """Mismatches should be detected, flagged, and written to the DB."""
    with Session(engine) as session:
        # DB has AAPL but T212 doesn't — position drift
        _make_db_position(session, "AAPL", "5")
        # DB has a submitted order with broker_id 99, T212 doesn't — order drift
        _make_db_order(session, "AAPL", broker_order_id="99")

    t212_client = _make_mock_t212(
        positions=[],  # T212 has no positions
        orders=[],  # T212 has no matching orders
    )

    row = run_reconciliation(t212_client=t212_client, engine=engine)

    assert row.status == "drift_detected"
    assert row.position_drifts == 1
    assert row.order_drifts == 1

    details = json.loads(row.details or "[]")
    drift_types = {d["type"] for d in details}
    assert "position_missing_in_t212" in drift_types
    assert "order_submitted_in_db_not_found_at_t212" in drift_types


def test_reconciliation_skips_position_check_when_db_unpopulated(engine: Engine) -> None:
    """Empty Position table → position check skipped, no false-positive drift.

    Nothing populates the Position table yet, so comparing it against live
    T212 holdings would flag every real holding as drift. The check is skipped
    until position tracking is wired up.
    """
    t212_client = _make_mock_t212(
        positions=[
            _make_t212_position("AAPL_US_EQ", "5"),
            _make_t212_position("MSFT_US_EQ", "10"),
        ],
        orders=[],
    )

    row = run_reconciliation(t212_client=t212_client, engine=engine)

    assert row.status == "ok"
    assert row.position_drifts == 0
    assert row.order_drifts == 0

    details = json.loads(row.details or "[]")
    assert any(d["type"] == "position_check_skipped" for d in details)


def test_reconciliation_error_scenario(engine: Engine) -> None:
    """If T212 call raises, status should be 'error' and it should still write to DB."""
    mock = MagicMock()
    mock.get_positions.side_effect = RuntimeError("T212 unavailable")

    row = run_reconciliation(t212_client=mock, engine=engine)

    assert row.status == "error"
    assert row.id is not None

    details = json.loads(row.details or "[]")
    assert any(d.get("type") == "error" for d in details)


def test_reconciliation_skipped_when_t212_key_unset(engine: Engine, monkeypatch) -> None:
    """No T212_API_KEY → status 'skipped', persisted, no doomed API call."""
    fake_settings = MagicMock()
    fake_settings.t212_api_key.get_secret_value.return_value = ""
    monkeypatch.setattr("ai_agent.reconciliation.get_settings", lambda: fake_settings)

    row = run_reconciliation(engine=engine)

    assert row.status == "skipped"
    assert row.id is not None
    details = json.loads(row.details or "[]")
    assert any(d.get("type") == "skipped" for d in details)
