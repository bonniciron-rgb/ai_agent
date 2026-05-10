"""Tests for the daily reasoning digest + cost alert."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, select

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import LlmUsage, Proposal, ProposalStatus, Setting
from ai_agent.digest.daily_digest import (
    DigestData,
    aggregate_digest,
    format_cost_alert_html,
    format_digest_html,
    run_daily_digest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIGEST_DATE = date(2026, 5, 9)
THRESHOLD = Decimal("5.00")


def _make_proposal(
    session: Session,
    *,
    symbol: str = "AAPL",
    side: str = "buy",
    quantity: str = "10",
    limit_price: str = "182.50",
    confidence: str = "high",
    status: ProposalStatus = ProposalStatus.proposed,
    rationale: str = "Strong momentum",
    created_at: datetime | None = None,
) -> Proposal:
    if created_at is None:
        created_at = datetime(2026, 5, 9, 14, 30, 0, tzinfo=UTC)
    p = Proposal(
        created_at=created_at,
        expires_at=created_at + timedelta(hours=4),
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=Decimal(quantity),
        limit_price=Decimal(limit_price),
        confidence=confidence,
        status=status,
        rationale=rationale,
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _make_usage(
    session: Session,
    *,
    occurred_on: date = DIGEST_DATE,
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read_input_tokens: int = 0,
    cost_usd: str = "0.10",
    pass_type: str = "screening",
    purpose: str = "test",
) -> LlmUsage:
    u = LlmUsage(
        occurred_on=occurred_on,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        cost_usd=Decimal(cost_usd),
        pass_type=pass_type,
        purpose=purpose,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _patch_get_session(monkeypatch, engine):
    """Monkeypatch ai_agent.db.engine.get_session to use *engine*."""
    import ai_agent.db.engine as eng_mod

    @contextmanager
    def _get_session(engine_arg=None) -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(eng_mod, "get_session", _get_session)


# ---------------------------------------------------------------------------
# Test 1: empty DB
# ---------------------------------------------------------------------------


def test_aggregate_empty_day(in_memory_engine) -> None:
    digest = aggregate_digest(DIGEST_DATE, THRESHOLD, engine=in_memory_engine)

    assert digest.proposal_count == 0
    assert digest.total_cost_usd == Decimal("0")
    assert digest.cache_hit_rate is None
    assert digest.cost_alert_triggered is False
    assert digest.proposals_by_status == {}
    assert digest.proposal_summaries == []
    assert digest.sample_rationale is None
    assert digest.total_calls == 0


# ---------------------------------------------------------------------------
# Test 2: proposals and usage on the digest date, plus excluded rows
# ---------------------------------------------------------------------------


def test_aggregate_with_proposals_and_usage(in_memory_engine) -> None:
    yesterday = DIGEST_DATE - timedelta(days=1)
    yesterday_dt = datetime(2026, 5, 8, 15, 0, 0, tzinfo=UTC)

    with Session(in_memory_engine) as session:
        # Two proposals on digest date
        p1 = _make_proposal(
            session,
            symbol="AAPL",
            side="buy",
            rationale="AAPL strong momentum",
            status=ProposalStatus.proposed,
            created_at=datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC),
        )
        _make_proposal(
            session,
            symbol="MSFT",
            side="sell",
            status=ProposalStatus.approved,
            rationale="MSFT overbought",
            created_at=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        )
        # One proposal from previous day — must be excluded
        _make_proposal(
            session,
            symbol="TSLA",
            side="buy",
            rationale="TSLA breakout",
            created_at=yesterday_dt,
        )

        # Three usage rows on digest date
        _make_usage(
            session,
            occurred_on=DIGEST_DATE,
            pass_type="screening",
            model="claude-haiku",
            input_tokens=200,
            cache_read_input_tokens=100,
            cost_usd="0.12",
        )
        _make_usage(
            session,
            occurred_on=DIGEST_DATE,
            pass_type="decision",
            model="claude-sonnet-4-6",
            input_tokens=300,
            cache_read_input_tokens=50,
            cost_usd="0.50",
        )
        _make_usage(
            session,
            occurred_on=DIGEST_DATE,
            pass_type="decision",
            model="claude-sonnet-4-6",
            input_tokens=400,
            cache_read_input_tokens=0,
            cost_usd="0.22",
        )
        # Usage from previous day — must be excluded
        _make_usage(
            session,
            occurred_on=yesterday,
            pass_type="screening",
            model="claude-haiku",
            input_tokens=999,
            cost_usd="9.99",
        )

    digest = aggregate_digest(DIGEST_DATE, THRESHOLD, engine=in_memory_engine)

    assert digest.proposal_count == 2
    assert digest.proposals_by_status == {"proposed": 1, "approved": 1}

    expected_total = Decimal("0.12") + Decimal("0.50") + Decimal("0.22")
    assert digest.total_cost_usd == expected_total

    assert digest.cost_by_pass["screening"] == Decimal("0.12")
    assert digest.cost_by_pass["decision"] == Decimal("0.50") + Decimal("0.22")

    assert digest.total_calls == 3

    # cache_hit_rate: total_cache_read = 100+50+0 = 150; total_input = 200+300+400 = 900
    # denominator = 150 + 900 = 1050
    # rate = 150/1050
    total_cache_read = 150
    total_input = 900
    expected_rate = total_cache_read / (total_cache_read + total_input)
    assert digest.cache_hit_rate == pytest.approx(expected_rate)

    # sample_rationale from first proposal (AAPL, created_at=10:00)
    assert digest.sample_rationale == "AAPL strong momentum"

    assert digest.cost_alert_triggered is False  # $0.84 < $5.00


# ---------------------------------------------------------------------------
# Test 3: format_digest_html with real data
# ---------------------------------------------------------------------------


def test_format_digest_html_basic(in_memory_engine) -> None:
    with Session(in_memory_engine) as session:
        _make_proposal(
            session,
            symbol="AAPL",
            side="buy",
            quantity="10",
            limit_price="182.50",
            confidence="high",
            status=ProposalStatus.proposed,
            rationale="<script>alert(1)</script> AAPL momentum",
        )
        _make_proposal(
            session,
            symbol="MSFT",
            side="buy",
            quantity="5",
            limit_price="415.00",
            confidence="medium",
            status=ProposalStatus.approved,
        )

    digest = aggregate_digest(DIGEST_DATE, THRESHOLD, engine=in_memory_engine)
    html_out = format_digest_html(digest)

    assert "2026-05-09" in html_out
    assert "2" in html_out  # proposal count
    assert "<b>" in html_out
    # XSS-dangerous content must be escaped
    assert "&lt;script&gt;" in html_out
    assert "<script>" not in html_out


# ---------------------------------------------------------------------------
# Test 4: format_digest_html with empty digest
# ---------------------------------------------------------------------------


def test_format_digest_html_empty(in_memory_engine) -> None:
    digest = aggregate_digest(DIGEST_DATE, THRESHOLD, engine=in_memory_engine)
    html_out = format_digest_html(digest)

    assert "No proposals today" in html_out
    assert "No LLM activity" in html_out


# ---------------------------------------------------------------------------
# Test 5: cost below threshold — no alert, one telegram call
# ---------------------------------------------------------------------------


def test_cost_alert_threshold_not_triggered(in_memory_engine, monkeypatch) -> None:
    mock_telegram = MagicMock()
    monkeypatch.setattr("ai_agent.digest.daily_digest._send_telegram", mock_telegram)
    _patch_get_session(monkeypatch, in_memory_engine)

    # Seed usage just below threshold ($4.99)
    with Session(in_memory_engine) as session:
        _make_usage(session, cost_usd="4.99")

    digest = run_daily_digest(
        digest_date=DIGEST_DATE,
        threshold=THRESHOLD,
        engine=in_memory_engine,
    )

    assert digest.cost_alert_triggered is False
    # Only one telegram call: the digest
    mock_telegram.assert_called_once()

    # Verify set_trading_halted was NOT called by checking DB
    with Session(in_memory_engine) as session:
        row = session.exec(select(Setting).where(Setting.key == "trading_halted")).first()
    assert row is None


# ---------------------------------------------------------------------------
# Test 6: cost above threshold — alert, two telegram calls, halt set
# ---------------------------------------------------------------------------


def test_cost_alert_threshold_triggered(in_memory_engine, monkeypatch) -> None:
    mock_telegram = MagicMock()
    monkeypatch.setattr("ai_agent.digest.daily_digest._send_telegram", mock_telegram)
    _patch_get_session(monkeypatch, in_memory_engine)

    # Seed usage above threshold ($5.50)
    with Session(in_memory_engine) as session:
        _make_usage(session, cost_usd="5.50")

    digest = run_daily_digest(
        digest_date=DIGEST_DATE,
        threshold=THRESHOLD,
        engine=in_memory_engine,
    )

    assert digest.cost_alert_triggered is True

    # Two telegram calls: alert first, then digest
    assert mock_telegram.call_count == 2
    first_call_msg = mock_telegram.call_args_list[0][0][0]
    assert "COST ALERT" in first_call_msg

    # Verify trading_halted was set in DB
    with Session(in_memory_engine) as session:
        row = session.exec(select(Setting).where(Setting.key == "trading_halted")).first()
    assert row is not None
    assert row.value == "1"
    assert row.updated_by == "cost_alert"


# ---------------------------------------------------------------------------
# Test 7: cost exactly at threshold triggers alert (>= boundary)
# ---------------------------------------------------------------------------


def test_cost_alert_threshold_exact(in_memory_engine, monkeypatch) -> None:
    mock_telegram = MagicMock()
    monkeypatch.setattr("ai_agent.digest.daily_digest._send_telegram", mock_telegram)
    _patch_get_session(monkeypatch, in_memory_engine)

    # Seed usage exactly at threshold
    with Session(in_memory_engine) as session:
        _make_usage(session, cost_usd="5.00")

    digest = run_daily_digest(
        digest_date=DIGEST_DATE,
        threshold=THRESHOLD,
        engine=in_memory_engine,
    )

    assert digest.cost_alert_triggered is True
    assert mock_telegram.call_count == 2


# ---------------------------------------------------------------------------
# Test 8: dry_run skips telegram and trading halt
# ---------------------------------------------------------------------------


def test_dry_run_skips_telegram_and_pause(in_memory_engine, monkeypatch) -> None:
    mock_telegram = MagicMock()
    monkeypatch.setattr("ai_agent.digest.daily_digest._send_telegram", mock_telegram)
    _patch_get_session(monkeypatch, in_memory_engine)

    # Seed usage well above threshold
    with Session(in_memory_engine) as session:
        _make_usage(session, cost_usd="10.00")

    digest = run_daily_digest(
        digest_date=DIGEST_DATE,
        threshold=Decimal("5.00"),
        engine=in_memory_engine,
        dry_run=True,
    )

    assert digest.cost_alert_triggered is True

    # Telegram must NOT have been called
    mock_telegram.assert_not_called()

    # trading_halted setting must NOT be present (or must be "0")
    with Session(in_memory_engine) as session:
        row = session.exec(select(Setting).where(Setting.key == "trading_halted")).first()
    assert row is None or row.value == "0"
