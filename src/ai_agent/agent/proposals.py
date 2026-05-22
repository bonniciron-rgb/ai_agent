"""Lightweight proposal model produced by the Claude agent.

Decoupled from the DB model so the agent layer has no SQLModel dependency.
A separate persistence layer converts these to db.models.Proposal rows.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, field_validator

from ai_agent.db.models import OrderSide


class TradeProposal(BaseModel):
    """One trade proposal returned by the Claude agent."""

    symbol: str
    side: OrderSide
    quantity: Decimal  # shares; fractional allowed (e.g. 0.8 to exit a fractional position)
    limit_price: Decimal
    stop_price: Decimal | None = None
    rationale: str
    confidence: str  # "high" | "medium" | "low"

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError(f"quantity must be positive, got {v}")
        return v

    @field_validator("confidence")
    @classmethod
    def valid_confidence(cls, v: str) -> str:
        if v not in ("high", "medium", "low"):
            raise ValueError(f"confidence must be high/medium/low, got {v!r}")
        return v
