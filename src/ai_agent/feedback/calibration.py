"""Closed-loop calibration: turn shadow outcomes into agent feedback.

The shadow-MTM job (``scripts/shadow_mtm.py`` + ``shadow-mtm.yml``) already
closes every proposal's hypothetical position after 5 trading days (or earlier
on TP/SL), writing ``ShadowPosition.pnl``. That gives us a per-proposal outcome
record covering BUYs, SELLs, approved, rejected — everything the agent has ever
proposed.

This module aggregates those closed shadows into a **calibration report** —
win rate and average return sliced by confidence tier, side, and active quant
signal — and renders it into:

  * a one-line snippet appended to the decision-pass user prompt so the agent
    sees how its recent calls have actually performed (closing the loop), and
  * a digest block surfaced in the daily Telegram digest.

Return convention: ``return_pct = pnl / opened_price``. ``pnl`` is already
side-adjusted by the shadow MTM (buy: close-open, sell: open-close), so a
positive number always means the trade decision was vindicated.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlmodel import Session, select

import ai_agent.db.engine as _engine
from ai_agent.db.models import Proposal, ShadowPosition, SignalSnapshot

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Don't surface stats to the agent below this sample count — too noisy to trust.
MIN_SAMPLES_FOR_PROMPT = 8


@dataclass
class CalibrationBucket:
    label: str
    n: int
    win_rate: float  # 0..1
    avg_return_pct: float  # e.g. 0.6 means +0.6%
    avg_pnl: float  # per-share, in account currency


@dataclass
class Calibration:
    as_of: date
    days_back: int
    overall: CalibrationBucket
    by_confidence: dict[str, CalibrationBucket] = field(default_factory=dict)
    by_side: dict[str, CalibrationBucket] = field(default_factory=dict)
    by_signal: dict[str, CalibrationBucket] = field(default_factory=dict)


@dataclass
class _Row:
    """A single closed-shadow observation feeding the aggregation."""

    return_pct: float  # decimal, e.g. 0.006 means +0.6%
    pnl: float
    confidence: str
    side: str
    opened_date: date
    symbol: str


def _bucket(label: str, rows: list[_Row]) -> CalibrationBucket:
    n = len(rows)
    if n == 0:
        return CalibrationBucket(label=label, n=0, win_rate=0.0, avg_return_pct=0.0, avg_pnl=0.0)
    wins = sum(1 for r in rows if r.pnl > 0)
    return CalibrationBucket(
        label=label,
        n=n,
        win_rate=wins / n,
        avg_return_pct=100.0 * sum(r.return_pct for r in rows) / n,
        avg_pnl=sum(r.pnl for r in rows) / n,
    )


def _collect_rows(session: Session, *, cutoff: datetime) -> list[_Row]:
    """Pull every closed ShadowPosition since *cutoff* and attach its Proposal."""
    shadows = session.exec(
        select(ShadowPosition).where(
            ShadowPosition.closed_at.is_not(None),  # type: ignore[union-attr]
            ShadowPosition.pnl.is_not(None),  # type: ignore[union-attr]
            ShadowPosition.closed_at >= cutoff,  # type: ignore[operator]
        )
    ).all()
    rows: list[_Row] = []
    for sh in shadows:
        if not sh.opened_price or sh.pnl is None:
            continue
        prop = session.get(Proposal, sh.proposal_id)
        rows.append(
            _Row(
                return_pct=sh.pnl / sh.opened_price,
                pnl=sh.pnl,
                confidence=(prop.confidence if prop and prop.confidence else "unknown"),
                side=sh.side,
                opened_date=sh.opened_at.date(),
                symbol=sh.symbol.upper(),
            )
        )
    return rows


def _by_signal_rows(session: Session, rows: list[_Row]) -> dict[str, list[_Row]]:
    """Group rows by the quant signals that were active at proposal-open time.

    Looks up the most-recent SignalSnapshot on or before each row's opened_date
    and routes the row into a bucket for every sub-signal whose score > 0.
    Returns ``{}`` when no SignalSnapshot rows exist yet (Batch 54 just landed,
    so the historical record is empty for now and the slice is silently absent).
    """
    out: dict[str, list[_Row]] = {}
    for row in rows:
        snap = session.exec(
            select(SignalSnapshot)
            .where(
                SignalSnapshot.symbol == row.symbol,
                SignalSnapshot.as_of <= row.opened_date,
            )
            .order_by(SignalSnapshot.as_of.desc())  # type: ignore[attr-defined]
            .limit(1)
        ).first()
        if snap is None:
            continue
        try:
            payload = json.loads(snap.signals_json)
        except json.JSONDecodeError:
            continue
        for name, sig in payload.items():
            try:
                score = float(sig.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            if score > 0:
                out.setdefault(name, []).append(row)
    return out


def compute_calibration(
    *,
    days_back: int = 90,
    as_of: date | None = None,
    engine: Engine | None = None,
) -> Calibration:
    """Aggregate closed ShadowPositions in the trailing *days_back* days."""
    as_of = as_of or datetime.now(UTC).date()
    cutoff = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC) - timedelta(days=days_back)
    eng = engine or _engine.get_engine()

    with Session(eng) as session:
        rows = _collect_rows(session, cutoff=cutoff)
        by_signal_rows = _by_signal_rows(session, rows)

    by_confidence: dict[str, CalibrationBucket] = {}
    for tier in ("high", "medium", "low"):
        bucket = _bucket(tier, [r for r in rows if r.confidence == tier])
        if bucket.n > 0:
            by_confidence[tier] = bucket

    by_side: dict[str, CalibrationBucket] = {}
    for side in ("buy", "sell"):
        bucket = _bucket(side, [r for r in rows if r.side == side])
        if bucket.n > 0:
            by_side[side] = bucket

    by_signal = {name: _bucket(name, rs) for name, rs in by_signal_rows.items() if rs}

    return Calibration(
        as_of=as_of,
        days_back=days_back,
        overall=_bucket("overall", rows),
        by_confidence=by_confidence,
        by_side=by_side,
        by_signal=by_signal,
    )


def _fmt(b: CalibrationBucket) -> str:
    return f"{b.label} {round(b.win_rate * 100)}% win/{b.avg_return_pct:+.2f}% (n={b.n})"


def format_calibration_line(
    cal: Calibration, *, min_samples: int = MIN_SAMPLES_FOR_PROMPT
) -> str | None:
    """A compact one/two-line summary suitable for the decision prompt.

    Returns None when the overall sample size is below ``min_samples`` — too
    little history to make a meaningful self-correction.
    """
    if cal.overall.n < min_samples:
        return None
    parts = [
        f"Your recent calibration (last {cal.days_back}d, n={cal.overall.n}): "
        f"overall {round(cal.overall.win_rate * 100)}% win, "
        f"{cal.overall.avg_return_pct:+.2f}% avg return."
    ]
    if cal.by_confidence:
        tiers = ", ".join(
            _fmt(cal.by_confidence[t]) for t in ("high", "medium", "low") if t in cal.by_confidence
        )
        parts.append(f"By confidence: {tiers}.")
    if cal.by_signal:
        top = sorted(cal.by_signal.values(), key=lambda b: (-b.win_rate, -b.n))[:3]
        parts.append("By active signal: " + ", ".join(_fmt(b) for b in top) + ".")
    return " ".join(parts)


def format_calibration_block(cal: Calibration) -> list[str]:
    """A digest-friendly multi-line block. Empty list when there is nothing yet."""
    if cal.overall.n == 0:
        return []
    lines = [
        f"<b>\U0001f50d Agent calibration (last {cal.days_back}d, n={cal.overall.n}):</b>",
        f"• Overall: {round(cal.overall.win_rate * 100)}% win, "
        f"{cal.overall.avg_return_pct:+.2f}% avg",
    ]
    for tier in ("high", "medium", "low"):
        if tier in cal.by_confidence:
            b = cal.by_confidence[tier]
            lines.append(
                f"• {tier}-conf: {round(b.win_rate * 100)}% win, "
                f"{b.avg_return_pct:+.2f}% avg (n={b.n})"
            )
    if cal.by_signal:
        top = sorted(cal.by_signal.values(), key=lambda b: (-b.win_rate, -b.n))[:3]
        lines.append("• Top signals when active:")
        for b in top:
            lines.append(
                f"  - {b.label}: {round(b.win_rate * 100)}% win, {b.avg_return_pct:+.2f}% (n={b.n})"
            )
    return lines
