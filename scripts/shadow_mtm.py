"""Daily mark-to-market job for shadow positions.

Reads all open ShadowPosition rows, fetches today's close from the Bar table
(no external API calls), updates mark_price/marked_at, and closes positions
where TP/SL has been crossed or 5 trading days have elapsed.

Usage::

    python scripts/shadow_mtm.py [--date YYYY-MM-DD]

The ``--date`` flag overrides the reference date (useful for back-testing
or re-processing historical data).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

# Allow running as a top-level script without an editable install
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlmodel import Session, select

from ai_agent.db.engine import get_engine, init_schema
from ai_agent.db.models import Bar, Proposal, ShadowPosition

logger = logging.getLogger(__name__)

# How many trading days before we auto-close a shadow position
SHADOW_MAX_TRADING_DAYS = 5


def _get_close_for_symbol(session: Session, symbol: str, ref_date: date) -> float | None:
    """Return the closing price from the Bar table on or before *ref_date*."""
    row = session.exec(
        select(Bar)
        .where(Bar.symbol == symbol, Bar.trading_date <= ref_date)
        .order_by(Bar.trading_date.desc())  # type: ignore[arg-type]
        .limit(1)
    ).first()
    if row is None:
        return None
    return float(row.close)


def _get_trading_days_between(
    session: Session, symbol: str, start: datetime, end: datetime
) -> int:
    """Count bar rows for *symbol* between *start* and *end* (inclusive)."""
    start_date = start.date()
    end_date = end.date()
    rows = session.exec(
        select(Bar).where(
            Bar.symbol == symbol,
            Bar.trading_date >= start_date,
            Bar.trading_date <= end_date,
        )
    ).all()
    return len(rows)


def _compute_pnl(side: str, opened_price: float, closed_price: float) -> float:
    """Return raw P&L per share/unit (positive = profit)."""
    if side == "buy":
        return closed_price - opened_price
    else:
        return opened_price - closed_price


def run_mtm(ref_date: date | None = None) -> None:
    """Main MTM routine.

    Parameters
    ----------
    ref_date:
        Date to use as 'today'.  Defaults to the current UTC date.
    """
    if ref_date is None:
        ref_date = datetime.now(UTC).date()

    logger.info("Shadow MTM starting for date=%s", ref_date)
    init_schema()
    engine = get_engine()

    with Session(engine) as session:
        # Load all open shadow positions
        open_shadows = session.exec(
            select(ShadowPosition).where(ShadowPosition.closed_at.is_(None))  # type: ignore[union-attr]
        ).all()

        logger.info("Found %d open shadow positions", len(open_shadows))

        for shadow in open_shadows:
            symbol = shadow.symbol
            close_price = _get_close_for_symbol(session, symbol, ref_date)
            if close_price is None:
                logger.warning("No bar found for %s on %s — skipping", symbol, ref_date)
                continue

            # Update mark price
            shadow.mark_price = close_price
            shadow.marked_at = datetime.now(UTC)
            session.add(shadow)

            # Fetch linked proposal to get TP/SL prices
            proposal: Proposal | None = session.get(Proposal, shadow.proposal_id)
            if proposal is None:
                logger.warning(
                    "Shadow #%d has no linked proposal #%d — skipping TP/SL check",
                    shadow.id,
                    shadow.proposal_id,
                )
                continue

            stop_price = float(proposal.stop_price) if proposal.stop_price else None
            # Approximate TP as 2x the risk (if stop available), or None
            if stop_price is not None:
                risk = abs(float(proposal.limit_price) - stop_price)
                if shadow.side == "buy":
                    take_profit = float(proposal.limit_price) + 2 * risk
                else:
                    take_profit = float(proposal.limit_price) - 2 * risk
            else:
                take_profit = None

            # Check SL crossing
            sl_crossed = False
            tp_crossed = False
            if stop_price is not None:
                if shadow.side == "buy" and close_price <= stop_price:
                    sl_crossed = True
                elif shadow.side == "sell" and close_price >= stop_price:
                    sl_crossed = True

            if take_profit is not None:
                if shadow.side == "buy" and close_price >= take_profit:
                    tp_crossed = True
                elif shadow.side == "sell" and close_price <= take_profit:
                    tp_crossed = True

            # Check 5-trading-day expiry: count bars between open date and ref_date
            ref_datetime = datetime(ref_date.year, ref_date.month, ref_date.day, tzinfo=UTC)
            trading_days_elapsed = _get_trading_days_between(
                session, symbol, shadow.opened_at, ref_datetime
            )
            expired = trading_days_elapsed >= SHADOW_MAX_TRADING_DAYS

            if sl_crossed or tp_crossed or expired:
                if sl_crossed:
                    close_reason = "stop_loss"
                    closing_price = stop_price  # type: ignore[assignment]
                elif tp_crossed:
                    close_reason = "take_profit"
                    closing_price = take_profit  # type: ignore[assignment]
                else:
                    close_reason = "expired"
                    closing_price = close_price

                shadow.closed_at = datetime.now(UTC)
                shadow.closed_price = closing_price
                shadow.pnl = _compute_pnl(shadow.side, shadow.opened_price, closing_price)
                if shadow.decision is None:
                    shadow.decision = "expired"
                logger.info(
                    "Closing shadow #%d (%s %s) reason=%s pnl=%.4f",
                    shadow.id,
                    shadow.side,
                    symbol,
                    close_reason,
                    shadow.pnl,
                )
                session.add(shadow)

        session.commit()
    logger.info("Shadow MTM complete")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Shadow position mark-to-market")
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Override the reference date (default: today UTC)",
    )
    args = parser.parse_args()

    ref_date: date | None = None
    if args.date:
        try:
            ref_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid date format: {args.date!r}. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

    run_mtm(ref_date=ref_date)


if __name__ == "__main__":
    main()
