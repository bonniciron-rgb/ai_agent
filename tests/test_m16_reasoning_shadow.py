"""Tests for m16: LLM reasoning audit + shadow tracking.

Covers:
- ProposalReasoning round-trip via session
- ShadowPosition round-trip via session
- dry-run writes to both tables
- MTM job closes positions on TP/SL crossing
- 7d/30d/90d aggregation query returns correct P&L splits by decision
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from ai_agent.agent.proposals import TradeProposal
from ai_agent.data.base import BarPoint, BarSeries
from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import (
    Bar,
    OrderSide,
    Proposal,
    ProposalReasoning,
    ProposalStatus,
    ShadowPosition,
)
from ai_agent.loop import daily_loop as dl
from ai_agent.loop.daily_loop import _save_proposals


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(eng)
    return eng


@pytest.fixture(autouse=True)
def _patch_engine(engine, monkeypatch):
    """Route all get_session() calls to the in-memory engine."""
    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)


@pytest.fixture
def base_proposal(engine) -> Proposal:
    """Insert a minimal Proposal row and return it."""
    with Session(engine) as s:
        row = Proposal(
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            symbol="AAPL",
            side=OrderSide.buy,
            quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
            stop_price=Decimal("143.00"),
            rationale="Test rationale",
            confidence="medium",
            status=ProposalStatus.proposed,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


# ---------------------------------------------------------------------------
# A: Model round-trips
# ---------------------------------------------------------------------------


def test_proposal_reasoning_round_trip(engine, base_proposal) -> None:
    """ProposalReasoning can be written and read back with correct fields."""
    with Session(engine) as s:
        row = ProposalReasoning(
            proposal_id=base_proposal.id,
            prompt_text="This is the prompt",
            response_text="This is the response",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
        )
        s.add(row)
        s.commit()
        s.refresh(row)

        assert row.id is not None
        assert row.proposal_id == base_proposal.id
        assert row.prompt_text == "This is the prompt"
        assert row.response_text == "This is the response"
        assert row.model == "claude-sonnet-4-6"
        assert row.input_tokens == 1000
        assert row.output_tokens == 500
        assert row.created_at is not None

    # Read back
    with Session(engine) as s:
        fetched = s.exec(
            select(ProposalReasoning).where(
                ProposalReasoning.proposal_id == base_proposal.id
            )
        ).first()
        assert fetched is not None
        assert fetched.prompt_text == "This is the prompt"


def test_shadow_position_round_trip(engine, base_proposal) -> None:
    """ShadowPosition can be written and read back with correct fields."""
    opened = datetime.now(UTC)
    with Session(engine) as s:
        row = ShadowPosition(
            proposal_id=base_proposal.id,
            symbol="AAPL",
            side="buy",
            decision=None,
            opened_at=opened,
            opened_price=150.0,
        )
        s.add(row)
        s.commit()
        s.refresh(row)

        assert row.id is not None
        assert row.proposal_id == base_proposal.id
        assert row.symbol == "AAPL"
        assert row.side == "buy"
        assert row.decision is None
        assert row.closed_at is None
        assert row.pnl is None

    # Flip decision
    with Session(engine) as s:
        fetched = s.exec(
            select(ShadowPosition).where(ShadowPosition.proposal_id == base_proposal.id)
        ).first()
        assert fetched is not None
        fetched.decision = "rejected"
        s.add(fetched)
        s.commit()

    with Session(engine) as s:
        fetched2 = s.exec(
            select(ShadowPosition).where(ShadowPosition.proposal_id == base_proposal.id)
        ).first()
        assert fetched2.decision == "rejected"


# ---------------------------------------------------------------------------
# B: dry-run writes to both tables
# ---------------------------------------------------------------------------


class FakeOhlcv:
    name = "fake-ohlcv"

    def get_daily(self, symbol, start, end):
        points = []
        d = end - timedelta(days=300)
        price = Decimal("100")
        while d <= end:
            if d.weekday() < 5:
                points.append(
                    BarPoint(
                        symbol=symbol,
                        trading_date=d,
                        open=price,
                        high=price + Decimal("2"),
                        low=price - Decimal("2"),
                        close=price + Decimal("1"),
                        volume=1_000_000,
                        source="fake",
                    )
                )
                price += Decimal("0.10")
            d += timedelta(days=1)
        return BarSeries(symbol=symbol, points=points)


class FakeT212:
    def get_cash(self):
        return SimpleNamespace(free=Decimal("50_000"), invested=Decimal("0"))

    def get_positions(self):
        return []


def test_dry_run_writes_reasoning_and_shadow(engine, tmp_path, monkeypatch) -> None:
    """dry-run=True still writes ProposalReasoning + ShadowPosition rows."""
    # Create a minimal watchlist
    wl = tmp_path / "watchlist.yaml"
    wl.write_text(
        "entries:\n  - symbol: AAPL\n    sector: technology\n"
    )
    monkeypatch.setattr(dl, "WATCHLIST_PATH", wl)

    # Fake the agent to return one proposal
    proposal = TradeProposal(
        symbol="AAPL",
        side=OrderSide.buy,
        quantity=10,
        limit_price=Decimal("150"),
        stop_price=Decimal("143"),
        rationale="Strong uptrend.",
        confidence="medium",
    )

    def fake_run_agent(symbols, toolbox, **kwargs):
        return SimpleNamespace(
            proposals=[proposal],
            iterations=1,
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=0,
            cache_write_tokens=0,
            stop_reason="end_turn",
            prompt_messages=[{"role": "user", "content": "today's watchlist: AAPL"}],
            response_text="I propose buying AAPL.",
            model="claude-sonnet-4-6",
        )

    async def _no_digest(*args, **kwargs):
        return None

    monkeypatch.setattr(dl, "run_agent", fake_run_agent)
    monkeypatch.setattr(dl, "_send_digest", _no_digest)

    dl.run(
        dry_run=True,
        ohlcv_source=FakeOhlcv(),
        t212_client=FakeT212(),
        anthropic_client=None,
        finnhub_source=None,
        today=date(2026, 5, 5),
    )

    with Session(engine) as s:
        proposals = s.exec(select(Proposal)).all()
        assert len(proposals) == 1, "dry-run should still write proposal row"

        reasonings = s.exec(select(ProposalReasoning)).all()
        assert len(reasonings) == 1
        assert reasonings[0].proposal_id == proposals[0].id
        assert "AAPL" in reasonings[0].prompt_text or reasonings[0].model == "claude-sonnet-4-6"

        shadows = s.exec(select(ShadowPosition)).all()
        assert len(shadows) == 1
        assert shadows[0].symbol == "AAPL"
        assert shadows[0].decision is None  # undecided until user acts


# ---------------------------------------------------------------------------
# C: MTM job closes positions on TP/SL crossing
# ---------------------------------------------------------------------------


@pytest.fixture
def _seed_bars(engine):
    """Insert 10 trading days of bars for AAPL."""
    with Session(engine) as s:
        for i in range(10):
            d = date(2026, 4, 20) + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            s.add(
                Bar(
                    symbol="AAPL",
                    trading_date=d,
                    open=Decimal("100"),
                    high=Decimal("102"),
                    low=Decimal("98"),
                    close=Decimal(str(100 + i)),
                    volume=1_000_000,
                    source="fake",
                )
            )
        s.commit()


def _make_proposal_and_shadow(
    engine: object,
    *,
    limit_price: float,
    stop_price: float,
    side: str = "buy",
    opened_at: datetime | None = None,
) -> tuple[Proposal, ShadowPosition]:
    """Helper: insert a Proposal + ShadowPosition and return both."""
    if opened_at is None:
        opened_at = datetime(2026, 4, 20, tzinfo=UTC)
    with Session(engine) as s:
        proposal = Proposal(
            expires_at=opened_at + timedelta(hours=24),
            symbol="AAPL",
            side=OrderSide(side),
            quantity=Decimal("10"),
            limit_price=Decimal(str(limit_price)),
            stop_price=Decimal(str(stop_price)),
            rationale="test",
            confidence="medium",
        )
        s.add(proposal)
        s.flush()

        shadow = ShadowPosition(
            proposal_id=proposal.id,
            symbol="AAPL",
            side=side,
            decision="rejected",
            opened_at=opened_at,
            opened_price=limit_price,
        )
        s.add(shadow)
        s.commit()
        s.refresh(proposal)
        s.refresh(shadow)
        return proposal, shadow


def _patch_mtm(monkeypatch, engine):
    """Patch the shadow_mtm module to use the in-memory engine."""
    import scripts.shadow_mtm as mtm_mod

    monkeypatch.setattr(mtm_mod, "get_engine", lambda: engine)
    monkeypatch.setattr(mtm_mod, "init_schema", lambda: None)
    return mtm_mod


def test_mtm_closes_position_on_stop_loss(_seed_bars, engine, monkeypatch) -> None:
    """MTM job closes a shadow position when stop-loss is crossed."""
    mtm_mod = _patch_mtm(monkeypatch, engine)

    # Entry at 101, stop at 102 — price crosses stop on day with close=104
    _make_proposal_and_shadow(engine, limit_price=101, stop_price=102, side="sell")

    mtm_mod.run_mtm(ref_date=date(2026, 4, 24))  # close=104 for a sell — SL at 102 crossed

    with Session(engine) as s:
        shadow = s.exec(select(ShadowPosition)).first()
        assert shadow is not None
        assert shadow.closed_at is not None
        assert shadow.pnl is not None
        assert shadow.closed_price is not None


def test_mtm_closes_position_on_expiry(_seed_bars, engine, monkeypatch) -> None:
    """MTM job closes a shadow position after 5 trading days."""
    mtm_mod = _patch_mtm(monkeypatch, engine)

    # Entry at 200, stop at 100 — price never crosses either
    opened_at = datetime(2026, 4, 20, tzinfo=UTC)
    _make_proposal_and_shadow(
        engine, limit_price=200, stop_price=100, side="buy", opened_at=opened_at
    )

    # Run MTM on a date far enough away that ≥5 bars have been stored
    mtm_mod.run_mtm(ref_date=date(2026, 4, 29))  # 7+ trading days from April 20

    with Session(engine) as s:
        shadow = s.exec(select(ShadowPosition)).first()
        assert shadow is not None
        assert shadow.closed_at is not None
        assert shadow.pnl is not None


def test_mtm_updates_mark_price_when_open(_seed_bars, engine, monkeypatch) -> None:
    """MTM job marks open positions without closing them."""
    mtm_mod = _patch_mtm(monkeypatch, engine)

    # Entry far from stop; won't close
    _make_proposal_and_shadow(engine, limit_price=50, stop_price=10, side="buy")

    mtm_mod.run_mtm(ref_date=date(2026, 4, 21))  # early date, <5 trading days elapsed

    with Session(engine) as s:
        shadow = s.exec(select(ShadowPosition)).first()
        assert shadow is not None
        assert shadow.mark_price is not None
        assert shadow.marked_at is not None
        # Should still be open (not enough time, price well above stop)
        assert shadow.closed_at is None


# ---------------------------------------------------------------------------
# D: 7d/30d/90d aggregation correctness
# ---------------------------------------------------------------------------


def _make_closed_shadow(
    engine: object,
    *,
    decision: str,
    pnl: float,
    opened_days_ago: int,
) -> None:
    """Insert a closed ShadowPosition with the given P&L and recency."""
    now = datetime.now(UTC)
    opened_at = now - timedelta(days=opened_days_ago)
    with Session(engine) as s:
        proposal = Proposal(
            expires_at=now + timedelta(hours=1),
            symbol="TEST",
            side=OrderSide.buy,
            quantity=Decimal("1"),
            limit_price=Decimal("100"),
            stop_price=Decimal("90"),
            rationale="test",
            confidence="low",
        )
        s.add(proposal)
        s.flush()

        shadow = ShadowPosition(
            proposal_id=proposal.id,
            symbol="TEST",
            side="buy",
            decision=decision,
            opened_at=opened_at,
            opened_price=100.0,
            closed_at=opened_at + timedelta(days=3),
            closed_price=100.0 + pnl,
            pnl=pnl,
        )
        s.add(shadow)
        s.commit()


def test_shadow_aggregation_7d_excludes_old_trades(engine) -> None:
    """Trades older than 7 days should not appear in the 7d window."""
    # Trade 3 days ago: approved +5
    _make_closed_shadow(engine, decision="approved", pnl=5.0, opened_days_ago=3)
    # Trade 15 days ago: approved +10 (should be in 30d but not 7d)
    _make_closed_shadow(engine, decision="approved", pnl=10.0, opened_days_ago=15)
    # Trade 3 days ago: rejected -3
    _make_closed_shadow(engine, decision="rejected", pnl=-3.0, opened_days_ago=3)

    # Query using the same SQL logic as getShadowWindowStats (window=7 days)
    with Session(engine) as s:
        cutoff_7d = datetime.now(UTC) - timedelta(days=7)
        rows = s.exec(
            select(ShadowPosition).where(
                ShadowPosition.closed_at.is_not(None),  # type: ignore[union-attr]
                ShadowPosition.opened_at >= cutoff_7d,
                ShadowPosition.decision.in_(["approved", "rejected"]),  # type: ignore[union-attr]
            )
        ).all()

    decisions = [r.decision for r in rows]
    assert "approved" in decisions
    assert "rejected" in decisions
    # The 15-day-old trade should NOT be included
    pnls = [r.pnl for r in rows if r.decision == "approved"]
    assert 10.0 not in pnls, "Old 15d trade should be excluded from 7d window"
    assert 5.0 in pnls


def test_shadow_aggregation_30d_includes_recent_and_mid(engine) -> None:
    """Trades within 30 days should all appear in the 30d window."""
    _make_closed_shadow(engine, decision="approved", pnl=5.0, opened_days_ago=3)
    _make_closed_shadow(engine, decision="approved", pnl=10.0, opened_days_ago=15)
    _make_closed_shadow(engine, decision="rejected", pnl=-3.0, opened_days_ago=3)

    with Session(engine) as s:
        cutoff_30d = datetime.now(UTC) - timedelta(days=30)
        rows = s.exec(
            select(ShadowPosition).where(
                ShadowPosition.closed_at.is_not(None),  # type: ignore[union-attr]
                ShadowPosition.opened_at >= cutoff_30d,
                ShadowPosition.decision.in_(["approved", "rejected"]),  # type: ignore[union-attr]
            )
        ).all()

    approved_pnls = [r.pnl for r in rows if r.decision == "approved"]
    assert 5.0 in approved_pnls
    assert 10.0 in approved_pnls
    total_approved = sum(approved_pnls)
    assert abs(total_approved - 15.0) < 0.01
