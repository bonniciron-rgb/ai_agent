from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from ai_agent.db import (
    Bar,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Proposal,
    ProposalStatus,
)


def test_bar_unique_constraint(in_memory_engine: Engine) -> None:
    with Session(in_memory_engine) as s:
        s.add(
            Bar(
                symbol="AAPL",
                trading_date=date(2026, 1, 5),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=1_000_000,
                source="yfinance",
            )
        )
        s.commit()
        bars = s.exec(select(Bar).where(Bar.symbol == "AAPL")).all()
        assert len(bars) == 1


def test_proposal_lifecycle(in_memory_engine: Engine) -> None:
    now = datetime.now(UTC)
    with Session(in_memory_engine) as s:
        proposal = Proposal(
            expires_at=now + timedelta(hours=1),
            symbol="MSFT",
            side=OrderSide.buy,
            quantity=Decimal("10"),
            limit_price=Decimal("400.00"),
            stop_price=Decimal("388.00"),
            rationale="test",
            confidence="medium",
        )
        s.add(proposal)
        s.commit()
        s.refresh(proposal)
        assert proposal.id is not None
        assert proposal.status is ProposalStatus.proposed

        proposal.status = ProposalStatus.approved
        proposal.decided_at = now
        s.add(proposal)
        s.commit()

        order = Order(
            proposal_id=proposal.id,
            symbol="MSFT",
            side=OrderSide.buy,
            order_type=OrderType.limit,
            quantity=Decimal("10"),
            limit_price=Decimal("400.00"),
            status=OrderStatus.submitted,
        )
        s.add(order)
        s.commit()
        s.refresh(order)
        assert order.proposal_id == proposal.id
