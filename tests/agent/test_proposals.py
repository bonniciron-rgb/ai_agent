"""Tests for TradeProposal validation."""

from decimal import Decimal

import pytest

from ai_agent.agent.proposals import TradeProposal
from ai_agent.db.models import OrderSide


def _proposal(**overrides) -> dict:
    base = {
        "symbol": "aapl",
        "side": OrderSide.buy,
        "quantity": 10,
        "limit_price": Decimal("150.00"),
        "rationale": "Strong uptrend with volume confirmation.",
        "confidence": "high",
    }
    return {**base, **overrides}


def test_symbol_uppercased() -> None:
    p = TradeProposal(**_proposal(symbol="aapl"))
    assert p.symbol == "AAPL"


def test_valid_confidence_values() -> None:
    for conf in ("high", "medium", "low"):
        p = TradeProposal(**_proposal(confidence=conf))
        assert p.confidence == conf


def test_invalid_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        TradeProposal(**_proposal(confidence="very_high"))


def test_stop_price_optional() -> None:
    p = TradeProposal(**_proposal())
    assert p.stop_price is None
    p2 = TradeProposal(**_proposal(stop_price=Decimal("145.00")))
    assert p2.stop_price == Decimal("145.00")


def test_sell_side() -> None:
    p = TradeProposal(**_proposal(side=OrderSide.sell))
    assert p.side == OrderSide.sell


def test_quantity_accepts_fractional() -> None:
    # Fractional positions (e.g. 0.8 shares) must survive intact so a full
    # exit sells exactly what is held rather than rounding up to a whole share.
    p = TradeProposal(**_proposal(quantity=Decimal("0.8")))
    assert p.quantity == Decimal("0.8")


def test_quantity_rejects_zero_and_negative() -> None:
    for bad in (0, Decimal("-1")):
        with pytest.raises(ValueError, match="quantity"):
            TradeProposal(**_proposal(quantity=bad))
