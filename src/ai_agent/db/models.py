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
    risk_score: int | None = Field(default=None)  # 1 (lowest) .. 5 (highest risk)
    risk_score_reason: str | None = Field(default=None, max_length=200)
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


class WatchlistTicker(SQLModel, table=True):
    """DB-backed watchlist of tickers the agent screens each day.

    Bootstrapped from config/watchlist.yaml on first read.  Editable from /watchlist UI.
    """

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, unique=True, max_length=16)
    sector: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    tags_json: str = Field(default="[]", max_length=512)  # JSON-encoded list[str]
    paused: bool = Field(default=False, index=True)
    added_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MacroRegimeSnapshot(SQLModel, table=True):
    """Daily classification of overall market regime (bull/bear/sideways/etc).

    Computed from SPY + ^VIX bars by ai_agent.macro.regime_detector.
    """

    id: int | None = Field(default=None, primary_key=True)
    as_of: date = Field(index=True, unique=True)
    regime: str = Field(max_length=16, index=True)
    spy_close: Decimal
    spy_sma_50: Decimal
    spy_sma_200: Decimal
    spy_above_200sma: bool
    spy_50_over_200sma: bool
    vix_close: Decimal
    vix_sma_20: Decimal | None = None
    notes_json: str = Field(default="[]", max_length=1024)
    created_at: datetime = Field(default_factory=_utcnow)


class ExposureSnapshot(SQLModel, table=True):
    """Daily exposure-manager decision: target SPY allocation from the composite signal.

    Written by ai_agent.exposure.job.persist_snapshot (via scripts/tilt_snapshot.py).
    Read by the daily digest and the /tilt dashboard.
    """

    id: int | None = Field(default=None, primary_key=True)
    as_of: date = Field(index=True, unique=True)
    composite_score: float  # universe-average composite score (raw)
    target_allocation: float  # fraction of capital to hold in SPY (e.g. 0.65)
    n_symbols: int  # universe symbols that had enough history to score
    score_ceiling: float = 1.0
    per_symbol_scores_json: str = Field(default="{}", max_length=2048)
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def allocation_pct(self) -> int:
        return round(self.target_allocation * 100)


class SignalSnapshot(SQLModel, table=True):
    """Per-symbol quant-signal scores for one day.

    Written by ai_agent.signals.snapshot_job (via scripts/compute_signals.py)
    on a daily cron BEFORE the trade loop. Read by the agent's
    get_quant_signals tool so the LLM sees event/positioning alpha
    (post-earnings drift, analyst-revision momentum, insider buying, short
    interest) that the pure-technical get_features snapshot lacks.
    """

    __table_args__ = (UniqueConstraint("symbol", "as_of", name="uq_signalsnapshot_symbol_date"),)

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=16)
    as_of: date = Field(index=True)
    composite_score: float  # equal-weight mean of the sub-signal scores, [0, 1]
    composite_confidence: float = 1.0
    active_count: int = 0  # number of sub-signals that fired (score > 0)
    signals_json: str = Field(default="{}", max_length=4096)  # {name: {score, confidence, notes}}
    created_at: datetime = Field(default_factory=_utcnow)


class DailyAnalysis(SQLModel, table=True):
    """One row per daily-loop run — the audit trail behind 'no trade today'.

    Written by ai_agent.loop.daily_loop on every live run, including when zero
    proposals pass. Read by the /analysis page and the daily digest so the user
    can always see what was considered and why nothing (or something) came out.
    """

    id: int | None = Field(default=None, primary_key=True)
    as_of: date = Field(index=True, unique=True)
    symbols_considered_json: str = Field(default="[]", max_length=4096)
    proposals_generated: int = 0  # raw proposals from the agent (pre risk filter)
    proposals_passed_risk: int = 0  # proposals that survived the risk rails
    proposals_blocked_risk: int = 0  # proposals the risk rails rejected
    agent_iterations: int = 0
    summary: str = Field(default="", max_length=8000)  # the agent's final reasoning text
    model: str = Field(default="unknown", max_length=64)
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def has_proposals(self) -> bool:
        return self.proposals_passed_risk > 0


class SignalBacktest(SQLModel, table=True):
    """Persisted backtest result for a (signal_name, version, period) tuple.

    Written by ai_agent.signals.runner.save_backtest_result.
    Acts as the historical record of how each candidate signal scored,
    used by the promotion gate (backtest >= baseline AND >= 2 weeks shadow >= baseline).
    """

    id: int | None = Field(default=None, primary_key=True)
    signal_name: str = Field(index=True, max_length=64)
    signal_version: str = Field(max_length=32)
    period_start: date
    period_end: date
    symbols_json: str  # JSON-encoded list[str]
    benchmark_symbol: str = Field(max_length=16)
    sharpe: float | None = None
    cagr: float | None = None
    max_drawdown: float | None = None
    win_rate: float | None = None
    alpha: float | None = None  # signal CAGR minus benchmark CAGR
    benchmark_sharpe: float | None = None
    benchmark_cagr: float | None = None
    trade_count: int = 0
    notes: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class PushSubscription(SQLModel, table=True):
    """Web Push subscription registered from a browser / installed PWA.

    One row per device endpoint.  Subscriptions are global (not per-user) to
    mirror the single-owner Telegram pattern; any installed device gets the
    daily digest push.
    """

    id: int | None = Field(default=None, primary_key=True)
    endpoint: str = Field(unique=True, max_length=512, index=True)
    auth_key: str = Field(max_length=128)
    p256dh_key: str = Field(max_length=128)
    user_agent: str | None = Field(default=None, max_length=256)
    created_at: datetime = Field(default_factory=_utcnow)
    last_used_at: datetime | None = None
