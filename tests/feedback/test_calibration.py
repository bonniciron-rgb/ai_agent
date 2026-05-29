"""Tests for the closed-loop calibration aggregator (Batch 55)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import (
    OrderSide,
    Proposal,
    ProposalStatus,
    ShadowPosition,
    SignalSnapshot,
)
from ai_agent.feedback.calibration import (
    compute_calibration,
    format_calibration_block,
    format_calibration_line,
)

AS_OF = date(2026, 5, 20)


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)
    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)

    @contextmanager
    def _get_session(engine_arg=None) -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(eng_mod, "get_session", _get_session)
    return engine


def _seed(
    session: Session,
    *,
    symbol: str = "AAPL",
    confidence: str = "high",
    side: str = "buy",
    opened_price: float = 100.0,
    pnl: float = 5.0,
    days_ago_opened: int = 6,
    days_ago_closed: int = 1,
) -> Proposal:
    opened_at = datetime.combine(
        AS_OF - timedelta(days=days_ago_opened), datetime.min.time()
    ).replace(tzinfo=UTC)
    closed_at = datetime.combine(
        AS_OF - timedelta(days=days_ago_closed), datetime.min.time()
    ).replace(tzinfo=UTC)
    prop = Proposal(
        expires_at=opened_at + timedelta(days=1),
        symbol=symbol,
        side=OrderSide(side),
        quantity=Decimal("1"),
        limit_price=Decimal(str(opened_price)),
        rationale="t",
        confidence=confidence,
        status=ProposalStatus.proposed,
    )
    session.add(prop)
    session.commit()
    session.refresh(prop)
    shadow = ShadowPosition(
        proposal_id=prop.id,
        symbol=symbol,
        side=side,
        opened_at=opened_at,
        opened_price=opened_price,
        closed_at=closed_at,
        closed_price=opened_price + (pnl if side == "buy" else -pnl),
        pnl=pnl,
    )
    session.add(shadow)
    session.commit()
    return prop


def test_no_data_returns_empty_calibration(_db) -> None:
    cal = compute_calibration(as_of=AS_OF)
    assert cal.overall.n == 0
    assert cal.by_confidence == {}
    assert cal.by_side == {}
    assert cal.by_signal == {}
    # Line is suppressed below the min-samples threshold.
    assert format_calibration_line(cal) is None
    assert format_calibration_block(cal) == []


def test_aggregates_overall_and_by_confidence(_db) -> None:
    with Session(_db) as s:
        _seed(s, symbol="AAA", confidence="high", pnl=5.0)
        _seed(s, symbol="BBB", confidence="high", pnl=2.0)
        _seed(s, symbol="CCC", confidence="high", pnl=-3.0)  # loss
        _seed(s, symbol="DDD", confidence="medium", pnl=-1.0)  # loss
        _seed(s, symbol="EEE", confidence="medium", pnl=4.0)

    cal = compute_calibration(as_of=AS_OF)
    assert cal.overall.n == 5
    assert cal.overall.win_rate == pytest.approx(3 / 5)

    assert cal.by_confidence["high"].n == 3
    assert cal.by_confidence["high"].win_rate == pytest.approx(2 / 3)
    assert cal.by_confidence["medium"].n == 2
    assert cal.by_confidence["medium"].win_rate == pytest.approx(1 / 2)


def test_aggregates_by_side(_db) -> None:
    with Session(_db) as s:
        _seed(s, symbol="AAA", side="buy", pnl=5.0)
        _seed(s, symbol="BBB", side="sell", pnl=2.0)
        _seed(s, symbol="CCC", side="sell", pnl=-1.0)

    cal = compute_calibration(as_of=AS_OF)
    assert cal.by_side["buy"].n == 1
    assert cal.by_side["sell"].n == 2
    assert cal.by_side["sell"].win_rate == pytest.approx(1 / 2)


def test_window_excludes_old_closes(_db) -> None:
    with Session(_db) as s:
        _seed(s, symbol="OLD", days_ago_opened=200, days_ago_closed=195, pnl=10.0)
        _seed(s, symbol="NEW", days_ago_opened=6, days_ago_closed=1, pnl=-1.0)

    cal = compute_calibration(as_of=AS_OF, days_back=30)
    assert cal.overall.n == 1
    assert cal.overall.win_rate == 0.0  # only the loss is in window


def test_by_signal_joins_signalsnapshot(_db) -> None:
    with Session(_db) as s:
        # Two wins where post_earnings_drift was active, one loss without it
        for sym in ("AAA", "BBB"):
            _seed(s, symbol=sym, pnl=3.0)
            s.add(
                SignalSnapshot(
                    symbol=sym,
                    as_of=AS_OF - timedelta(days=7),  # <= opened_date
                    composite_score=0.5,
                    composite_confidence=1.0,
                    active_count=1,
                    signals_json=json.dumps(
                        {"post_earnings_drift": {"score": 1.0, "confidence": 1.0, "notes": []}}
                    ),
                )
            )
        _seed(s, symbol="CCC", pnl=-2.0)  # no snapshot
        s.commit()

    cal = compute_calibration(as_of=AS_OF)
    assert "post_earnings_drift" in cal.by_signal
    bucket = cal.by_signal["post_earnings_drift"]
    assert bucket.n == 2
    assert bucket.win_rate == 1.0


def test_format_line_below_threshold_returns_none(_db) -> None:
    with Session(_db) as s:
        _seed(s, symbol="X", pnl=1.0)  # only 1 sample, well below threshold
    cal = compute_calibration(as_of=AS_OF)
    assert format_calibration_line(cal) is None


def test_format_line_above_threshold(_db) -> None:
    with Session(_db) as s:
        for i in range(10):
            _seed(s, symbol=f"S{i}", pnl=1.0 if i < 6 else -1.0)
    cal = compute_calibration(as_of=AS_OF)
    line = format_calibration_line(cal)
    assert line is not None
    assert "n=10" in line
    assert "60% win" in line


def test_format_block_renders_when_data_present(_db) -> None:
    with Session(_db) as s:
        for i in range(3):
            _seed(s, symbol=f"S{i}", pnl=1.0)
    cal = compute_calibration(as_of=AS_OF)
    block = format_calibration_block(cal)
    assert block  # non-empty
    assert any("Agent calibration" in line for line in block)
