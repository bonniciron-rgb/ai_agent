"""Persist OHLCV bars to the DB and read them back as BarSeries.

The daily cron calls :func:`ingest_bars` once per run for all watchlist
symbols, then :func:`bars_from_db` is used by ``get_features`` and the
risk-rail ATR calculation.

Idempotent: ``UniqueConstraint("symbol", "trading_date")`` on the Bar table
means re-runs of the same day are safe — duplicate rows are silently skipped.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from ai_agent.data.base import BarPoint, BarSeries

# Module import so monkeypatched ``get_session`` in tests is always honoured.
from ai_agent.db import engine as _engine
from ai_agent.db.models import Bar

if TYPE_CHECKING:
    from ai_agent.data.base import OhlcvSource

logger = logging.getLogger(__name__)


def ingest_bars(
    symbols: list[str],
    *,
    source: OhlcvSource,
    days_back: int = 300,
    today: date | None = None,
) -> int:
    """Fetch bars for *symbols* and insert any that aren't already in the DB.

    Returns the total count of newly inserted bar rows.
    """
    end = today or date.today()
    start = end - timedelta(days=days_back)
    inserted = 0

    for symbol in symbols:
        try:
            series = source.get_daily(symbol, start, end)
        except Exception as exc:
            logger.warning("Bar ingest failed for %s: %s", symbol, exc)
            continue

        with _engine.get_session() as session:
            existing_dates = set(
                session.exec(  # type: ignore[call-overload]
                    select(Bar.trading_date).where(Bar.symbol == symbol.upper())
                ).all()
            )
            new_rows = [
                Bar(
                    symbol=p.symbol,
                    trading_date=p.trading_date,
                    open=p.open,
                    high=p.high,
                    low=p.low,
                    close=p.close,
                    adj_close=p.adj_close,
                    volume=p.volume,
                    source=p.source,
                )
                for p in series.points
                if p.trading_date not in existing_dates
            ]
            if not new_rows:
                continue
            try:
                session.add_all(new_rows)
                session.commit()
                inserted += len(new_rows)
            except IntegrityError as exc:
                session.rollback()
                logger.warning("Duplicate bars for %s — skipping: %s", symbol, exc)

    logger.info("Bar ingest: inserted %d rows across %d symbols", inserted, len(symbols))
    return inserted


def bars_from_db(
    symbol: str,
    *,
    days_back: int = 300,
    ref_date: date | None = None,
) -> BarSeries:
    """Read the last *days_back* days of bars for *symbol* from the DB."""
    end = ref_date or date.today()
    start = end - timedelta(days=days_back)

    with _engine.get_session() as session:
        rows = session.exec(
            select(Bar)
            .where(
                Bar.symbol == symbol.upper(),
                Bar.trading_date >= start,
                Bar.trading_date <= end,
            )
            .order_by(Bar.trading_date.asc())  # type: ignore[arg-type]
        ).all()

    points = [
        BarPoint(
            symbol=r.symbol,
            trading_date=r.trading_date,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            adj_close=r.adj_close,
            volume=r.volume,
            source=r.source,
        )
        for r in rows
    ]
    return BarSeries(symbol=symbol.upper(), points=points)
