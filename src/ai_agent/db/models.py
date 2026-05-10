from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel, UniqueConstraint


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OrderSide(StrEnum):
    buy = "buy"
    sell = "sell"


class OrderType(StrEnum):
    limit = "limit"
    stop = "stop"
    stop_limit = "stop_limit"
    market = "market"


class OrderStatus(StrEnum):
    pending = "pending"
    submitted = "submitted"
    filled = "filled"
    partially_filled = "partially_filled"
    cancelled = "cancelled"
    rejected = "rejected"
    expired = "expired"


class ProposalStatus(StrEnum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    deferred = "deferred"
    expired = "expired"
    executed = "executed"


class Bar(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("symbol", "trading_date", name="uq_bar_symbol_date"),)

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=16)
    trading_date: date = Field(index=True)
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal | None = None
    volume: int
    source: str = Field(max_length=32)
    ingested_at: datetime = Field(default_factory=_utcnow)


class Proposal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    expires_at: datetime
    symbol: str = Field(index=True, max_length=16)
    side: OrderSide
    quantity: Decimal
    limit_price: Decimal
    stop_price: Decimal | None = None
    rationale: str
    confidence: str = Field(max_length=16)
    status: ProposalStatus = Field(default=ProposalStatus.proposed, index=True)
    decided_at: datetime | None = None
    decided_by: str | None = Field(default=None, max_length=64)


class Order(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    proposal_id: int | None = Field(default=None, foreign_key="proposal.id", index=True)
    broker_order_id: str | None = Field(default=None, index=True, max_length=64)
    symbol: str = Field(index=True, max_length=16)
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    status: OrderStatus = Field(default=OrderStatus.pending, index=True)
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    filled_quantity: Decimal = Decimal(0)
    avg_fill_price: Decimal | None = None
    raw_response: str | None = None
    idempotency_key: str | None = Field(default=None, unique=True, index=True, max_length=64)


class Position(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=16, unique=True)
    quantity: Decimal
    avg_price: Decimal
    sector: str | None = Field(default=None, max_length=32)
    last_synced_at: datetime = Field(default_factory=_utcnow)


class LlmUsage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    occurred_on: date = Field(index=True)
    model: str = Field(max_length=64)
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal
    purpose: str = Field(max_length=64)
    # m18: tiered routing — "screening" | "decision" | "other"
    pass_type: str = Field(default="other", max_length=16, index=True)
    cache_creation_tokens: int = Field(default=0)
    cache_read_input_tokens: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utcnow)


class ExternalMessage(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("channel", "message_id", name="uq_ext_msg_channel_id"),)

    id: int | None = Field(default=None, primary_key=True)
    channel: str = Field(index=True, max_length=64)
    message_id: int = Field(index=True)
    posted_at: datetime = Field(index=True)
    text: str
    processed: bool = False
    ingested_at: datetime = Field(default_factory=_utcnow)


class ExternalSignal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    external_message_id: int = Field(foreign_key="externalmessage.id", index=True)
    channel: str = Field(index=True, max_length=64)
    posted_at: datetime = Field(index=True)
    symbol: str = Field(index=True, max_length=16)
    side: str = Field(max_length=8)
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    conviction: str | None = Field(default=None, max_length=16)
    notes: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class SignalChannel(SQLModel, table=True):
    """DB-backed list of Telegram channels to ingest signals from.

    Bootstrapped from config/external_signals.yaml on first ingest run.
    """

    id: int | None = Field(default=None, primary_key=True)
    handle: str = Field(index=True, unique=True, max_length=64)
    paused: bool = Field(default=False, index=True)
    added_at: datetime = Field(default_factory=_utcnow)
    last_run_at: datetime | None = None


class Setting(SQLModel, table=True):
    """Key-value runtime settings (halt flag, etc.) — toggleable from Telegram."""

    key: str = Field(primary_key=True, max_length=64)
    value: str = Field(max_length=256)
    updated_at: datetime = Field(default_factory=_utcnow)
    updated_by: str | None = Field(default=None, max_length=64)


class Reconciliation(SQLModel, table=True):
    """Record of each nightly reconciliation run comparing DB state with T212."""

    id: int | None = Field(default=None, primary_key=True)
    run_at: datetime = Field(default_factory=_utcnow, index=True)
    status: str = Field(max_length=16, index=True)  # "ok" | "drift_detected" | "error"
    position_drifts: int = 0
    order_drifts: int = 0
    details: str | None = None  # JSON dump of mismatches for forensic review


class ProposalReasoning(SQLModel, table=True):
    """Full LLM prompt + response captured for every proposal the agent emits.

    Written even in dry-run mode so we can audit reasoning quality offline.
    """

    id: int | None = Field(default=None, primary_key=True)
    proposal_id: int = Field(foreign_key="proposal.id", index=True)
    prompt_text: str = Field(sa_column=Column(Text, nullable=False))
    response_text: str = Field(sa_column=Column(Text, nullable=False))
    model: str = Field(max_length=64)
    input_tokens: int
    output_tokens: int
    created_at: datetime = Field(default_factory=_utcnow)


class ShadowDecision(StrEnum):
    approved = "approved"
    rejected = "rejected"
    edited = "edited"
    expired = "expired"


class ShadowPosition(SQLModel, table=True):
    """Hypothetical P&L tracker for every proposal, regardless of approval.

    Opened when a proposal is created; decision flipped when the user acts;
    closed when TP/SL is hit or after 5 trading days.
    """

    id: int | None = Field(default=None, primary_key=True)
    proposal_id: int = Field(foreign_key="proposal.id", index=True)
    symbol: str = Field(index=True, max_length=16)
    side: str = Field(max_length=8)  # "buy" | "sell"
    decision: str | None = Field(default=None, max_length=16)  # ShadowDecision or None
    opened_at: datetime = Field(default_factory=_utcnow)
    opened_price: float  # proposed limit price; falls back to that day's close
    closed_at: datetime | None = None
    closed_price: float | None = None
    pnl: float | None = None  # computed when closed
    mark_price: float | None = None  # last mark-to-market close
    marked_at: datetime | None = None
