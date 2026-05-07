"""Pydantic transport models for external signal ingestion.

These are separate from the SQLModel DB tables in ``db/models.py`` so the
parsing layer has no direct database dependency.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator


class RawMessage(BaseModel):
    """A single message fetched from a Telegram channel."""

    message_id: int
    channel: str
    posted_at: datetime
    text: str


class ParsedSignal(BaseModel):
    """Structured trade idea extracted from a raw message."""

    symbol: str
    side: str  # "buy" | "sell" | "watch"
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    conviction: str | None = None  # "high" | "medium" | "low"
    notes: str | None = None

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("side")
    @classmethod
    def _validate_side(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in ("buy", "sell", "watch"):
            raise ValueError(f"side must be buy/sell/watch, got {v!r}")
        return v

    @field_validator("conviction")
    @classmethod
    def _validate_conviction(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.lower().strip()
        if v not in ("high", "medium", "low"):
            raise ValueError(f"conviction must be high/medium/low, got {v!r}")
        return v
