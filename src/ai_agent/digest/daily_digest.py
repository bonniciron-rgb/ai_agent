"""Daily reasoning digest + cost alert.

Aggregates today's proposals and LLM cost, sends a Telegram summary, and
auto-pauses trading if the daily cost meets or exceeds
``DAILY_COST_ALERT_USD`` (default $5.00).

Run::

    python -m ai_agent.digest.daily_digest
    # or
    python scripts/daily_digest.py
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from ai_agent.db.engine import get_engine, init_schema
from ai_agent.db.models import ExposureSnapshot, LlmUsage, Proposal
from ai_agent.db.settings_store import set_trading_halted

if TYPE_CHECKING:
    from ai_agent.digest.push_sender import PushPayload

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ProposalSummary:
    symbol: str
    side: str
    quantity: Decimal
    limit_price: Decimal
    confidence: str
    status: str
    rationale: str  # truncated to 200 chars
    risk_score: int | None = None  # 1 (lowest) .. 5 (highest risk)


@dataclass
class DigestData:
    digest_date: date
    proposal_count: int
    proposals_by_status: dict[str, int]
    proposal_summaries: list[ProposalSummary]
    total_cost_usd: Decimal
    cost_by_pass: dict[str, Decimal]
    cost_by_model: dict[str, Decimal]
    total_calls: int
    cache_hit_rate: float | None  # cache_read / (cache_read + input); None if denominator=0
    sample_rationale: str | None  # rationale of first proposal, truncated to 240 chars
    cost_threshold: Decimal
    cost_alert_triggered: bool
    # Exposure-manager tilt (latest persisted ExposureSnapshot); None if none yet.
    exposure_alloc_pct: int | None = None
    exposure_composite: float | None = None
    exposure_n_symbols: int | None = None


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_digest(
    digest_date: date,
    threshold: Decimal,
    *,
    engine=None,
) -> DigestData:
    """Query the DB and compute all digest fields for the given date."""
    eng = engine or get_engine()

    day_start = datetime.combine(digest_date, time.min, tzinfo=UTC)
    day_end = datetime.combine(digest_date + timedelta(days=1), time.min, tzinfo=UTC)

    with Session(eng) as session:
        # --- Proposals ---
        proposals = list(
            session.exec(
                select(Proposal)
                .where(
                    Proposal.created_at >= day_start,
                    Proposal.created_at < day_end,
                )
                .order_by(Proposal.created_at)
            ).all()
        )

        # --- LLM Usage ---
        usages = list(
            session.exec(select(LlmUsage).where(LlmUsage.occurred_on == digest_date)).all()
        )

        # --- Exposure tilt (latest snapshot) ---
        tilt_row = session.exec(
            select(ExposureSnapshot).order_by(ExposureSnapshot.as_of.desc())  # type: ignore[attr-defined]
        ).first()

    # Compute proposal aggregates
    proposals_by_status: dict[str, int] = {}
    for p in proposals:
        key = str(p.status)
        proposals_by_status[key] = proposals_by_status.get(key, 0) + 1

    summaries: list[ProposalSummary] = [
        ProposalSummary(
            symbol=p.symbol,
            side=str(p.side),
            quantity=p.quantity,
            limit_price=p.limit_price,
            confidence=p.confidence,
            status=str(p.status),
            rationale=p.rationale[:200],
            risk_score=getattr(p, "risk_score", None),
        )
        for p in proposals[:5]
    ]

    sample_rationale: str | None = None
    if proposals:
        sample_rationale = proposals[0].rationale[:240]

    # Compute cost aggregates
    total_cost_usd = sum((u.cost_usd for u in usages), Decimal("0"))
    cost_by_pass: dict[str, Decimal] = {}
    cost_by_model: dict[str, Decimal] = {}
    total_calls = len(usages)

    total_cache_read = 0
    total_input = 0
    for u in usages:
        pt = u.pass_type
        cost_by_pass[pt] = cost_by_pass.get(pt, Decimal("0")) + u.cost_usd
        m = u.model
        cost_by_model[m] = cost_by_model.get(m, Decimal("0")) + u.cost_usd
        total_cache_read += u.cache_read_tokens + u.cache_read_input_tokens
        total_input += u.input_tokens

    denominator = total_cache_read + total_input
    cache_hit_rate: float | None = total_cache_read / denominator if denominator > 0 else None

    cost_alert_triggered = total_cost_usd >= threshold

    return DigestData(
        digest_date=digest_date,
        proposal_count=len(proposals),
        proposals_by_status=proposals_by_status,
        proposal_summaries=summaries,
        total_cost_usd=total_cost_usd,
        cost_by_pass=cost_by_pass,
        cost_by_model=cost_by_model,
        total_calls=total_calls,
        cache_hit_rate=cache_hit_rate,
        sample_rationale=sample_rationale,
        cost_threshold=threshold,
        cost_alert_triggered=cost_alert_triggered,
        exposure_alloc_pct=(tilt_row.allocation_pct if tilt_row is not None else None),
        exposure_composite=(tilt_row.composite_score if tilt_row is not None else None),
        exposure_n_symbols=(tilt_row.n_symbols if tilt_row is not None else None),
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_digest_html(digest: DigestData) -> str:
    """Render the daily digest as Telegram-compatible HTML."""
    date_str = digest.digest_date.strftime("%Y-%m-%d")
    lines: list[str] = [f"<b>\U0001f4ca Daily Agent Digest — {date_str}</b>", ""]

    # Proposals section
    lines.append(f"<b>\U0001f916 Proposals:</b> {digest.proposal_count}")
    if digest.proposal_count == 0:
        lines.append("• <i>No proposals today</i>")
    else:
        for s in digest.proposal_summaries:
            price = f"${s.limit_price:,.2f}"
            risk = f" risk {s.risk_score}/5" if s.risk_score is not None else ""
            lines.append(
                f"• {s.side.upper()} {s.symbol} {s.quantity} @ {price}"
                f" ({s.confidence}{risk}) — {s.status}"
            )

    lines.append("")

    # Cost section
    cost_str = f"${digest.total_cost_usd:,.2f}"
    lines.append(f"<b>\U0001f4b0 LLM Cost:</b> {cost_str}")
    if digest.total_cost_usd == 0:
        lines.append("• <i>No LLM activity</i>")
    else:
        for pt, cost in digest.cost_by_pass.items():
            lines.append(f"• {pt}: ${cost:,.2f}")
        if digest.cache_hit_rate is not None:
            rate_pct = digest.cache_hit_rate * 100
            lines.append(f"• Cache hit rate: {rate_pct:.1f}%")

    # Exposure-manager tilt section
    if digest.exposure_alloc_pct is not None:
        lines.append("")
        lines.append("<b>\U0001f4c8 Exposure tilt:</b>")
        composite = digest.exposure_composite if digest.exposure_composite is not None else 0.0
        n = digest.exposure_n_symbols if digest.exposure_n_symbols is not None else 0
        lines.append(f"• {digest.exposure_alloc_pct}% SPY (composite {composite:+.2f}, {n} names)")

    # Sample rationale section
    if digest.sample_rationale is not None:
        lines.append("")
        lines.append("<b>\U0001f9e0 Sample reasoning:</b>")
        escaped = html.escape(digest.sample_rationale)
        lines.append(f'<i>"{escaped}"</i>')

    return "\n".join(lines)


def format_cost_alert_html(digest: DigestData) -> str:
    """Render the cost alert as Telegram-compatible HTML."""
    spent = f"${digest.total_cost_usd:,.2f}"
    threshold = f"${digest.cost_threshold:,.2f}"
    return (
        "<b>\U0001f6a8 COST ALERT</b>\n"
        f"Spent <b>{spent}</b> today (threshold {threshold}).\n"
        "\U0001f6d1 Trading auto-paused. Resume with /resume."
    )


# ---------------------------------------------------------------------------
# Telegram helper (self-contained, mirrors reconciliation.py)
# ---------------------------------------------------------------------------


def format_digest_summary(digest: DigestData) -> PushPayload:
    from ai_agent.digest.push_sender import PushPayload

    n = digest.proposal_count
    spend = f"${digest.total_cost_usd:.2f}"
    if n == 0:
        body = f"No proposals today. LLM spend: {spend}."
    else:
        body = f"{n} proposal{'s' if n != 1 else ''} ready. LLM spend: {spend}."
    return PushPayload(
        title="Ethera daily digest",
        body=body,
        url="/proposals",
    )


def format_cost_alert_summary(digest: DigestData) -> PushPayload:
    from ai_agent.digest.push_sender import PushPayload

    return PushPayload(
        title="Ethera cost alert",
        body=(
            f"Daily LLM spend ${digest.total_cost_usd:.2f} exceeded threshold"
            f" ${digest.cost_threshold:.2f}. Trading paused."
        ),
        url="/llm-usage",
    )


def _send_web_push_safe(payload: PushPayload) -> None:
    try:
        from ai_agent.digest.push_sender import send_to_all

        send_to_all(payload)
    except Exception as exc:
        logger.warning("Web push delivery failed: %s", exc)


def _send_telegram(message: str) -> None:
    """Send a Telegram message via Bot API.  Logs and continues on any failure."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping alert")
        return
    try:
        import httpx

        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=15.0,
        )
        r.raise_for_status()
        logger.info("Telegram message sent")
    except Exception as exc:
        logger.error("Failed to send Telegram message: %s", exc)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_daily_digest(
    *,
    digest_date: date | None = None,
    threshold: Decimal | None = None,
    engine=None,
    dry_run: bool = False,
) -> DigestData:
    """Run the full digest pipeline and return the DigestData.

    Parameters
    ----------
    digest_date:
        Date to aggregate.  Defaults to today (UTC).
    threshold:
        Cost threshold in USD.  Defaults to ``DAILY_COST_ALERT_USD`` env var
        or ``5.00``.
    engine:
        Optional SQLAlchemy engine (for testing).
    dry_run:
        If True, skip Telegram messages and skip trading halt.
    """
    if digest_date is None:
        digest_date = datetime.now(UTC).date()
    if threshold is None:
        threshold = Decimal(os.environ.get("DAILY_COST_ALERT_USD", "5.00"))

    digest = aggregate_digest(digest_date, threshold, engine=engine)

    if digest.cost_alert_triggered and not dry_run:
        set_trading_halted(True, updated_by="cost_alert")
        _send_telegram(format_cost_alert_html(digest))
        _send_web_push_safe(format_cost_alert_summary(digest))

    if not dry_run:
        _send_telegram(format_digest_html(digest))
        _send_web_push_safe(format_digest_summary(digest))

    return digest


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily reasoning digest + cost alert")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and log without sending Telegram messages or pausing trading",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Override digest date (default: today UTC)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    digest_date: date | None = None
    if args.date:
        digest_date = date.fromisoformat(args.date)

    logger.info("Daily digest job starting (dry_run=%s, date=%s)", args.dry_run, digest_date)
    init_schema()

    digest = run_daily_digest(digest_date=digest_date, dry_run=args.dry_run)

    logger.info(
        "Daily digest complete: date=%s proposals=%d cost=$%s alert=%s",
        digest.digest_date,
        digest.proposal_count,
        digest.total_cost_usd,
        digest.cost_alert_triggered,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
