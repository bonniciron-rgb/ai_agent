"""LivePortfolioSnapshot — PortfolioSnapshot backed by T212 + Postgres.

Implements the PortfolioSnapshot protocol from ai_agent.risk.rails so the
RiskChecker can validate proposals against real portfolio state.

ATR values are read from the local features pipeline (last computed bar).
Sector data comes from the watchlist YAML file (Position.sector column as
fallback if the watchlist doesn't know the ticker).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlmodel import select

from ai_agent.broker.fx import get_gbp_rates, to_gbp
from ai_agent.db.engine import get_session
from ai_agent.db.models import Bar, Order, OrderSide, OrderStatus, Position

logger = logging.getLogger(__name__)


class LivePortfolioSnapshot:
    """Read portfolio state once on construction; answers risk-rail queries."""

    def __init__(
        self,
        t212_client,  # T212Client instance
        watchlist_sectors: dict[str, str] | None = None,
        reference_date: date | None = None,
    ) -> None:
        self._sectors = watchlist_sectors or {}
        self._ref_date = reference_date or datetime.now(UTC).date()
        self._nav, self._positions, self._db_sectors = self._load_from_t212(t212_client)

    # ------------------------------------------------------------------
    # PortfolioSnapshot protocol
    # ------------------------------------------------------------------

    @property
    def nav(self) -> Decimal:
        return self._nav

    def position_value(self, symbol: str) -> Decimal:
        return self._positions.get(symbol.upper(), Decimal("0"))

    def sector_value(self, sector: str) -> Decimal:
        total = Decimal("0")
        for sym, val in self._positions.items():
            if self.symbol_sector(sym) == sector:
                total += val
        return total

    def symbol_sector(self, symbol: str) -> str | None:
        sym = symbol.upper()
        return self._sectors.get(sym) or self._db_sectors.get(sym)

    def daily_turnover(self) -> Decimal:
        """Sum notional of orders submitted today (from DB)."""
        today_start = datetime.combine(self._ref_date, datetime.min.time()).replace(tzinfo=UTC)
        with get_session() as session:
            stmt = select(Order).where(
                Order.submitted_at >= today_start,
                Order.status.in_(  # type: ignore[attr-defined]
                    [OrderStatus.submitted, OrderStatus.filled, OrderStatus.partially_filled]
                ),
            )
            orders = session.exec(stmt).all()
        total = Decimal("0")
        for o in orders:
            price = o.limit_price or Decimal("0")
            total += price * o.quantity
        return total

    def days_since_last_sell(self, symbol: str) -> int | None:
        """Trading days since the last filled SELL order for *symbol*."""
        with get_session() as session:
            stmt = (
                select(Order)
                .where(
                    Order.symbol == symbol.upper(),
                    Order.side == OrderSide.sell,
                    Order.status == OrderStatus.filled,
                    Order.filled_at.is_not(None),  # type: ignore[attr-defined]
                )
                .order_by(Order.filled_at.desc())  # type: ignore[attr-defined]
                .limit(1)
            )
            last_sell = session.exec(stmt).first()

        if last_sell is None or last_sell.filled_at is None:
            return None

        last_date = last_sell.filled_at.date()
        return _trading_days_between(last_date, self._ref_date)

    def atr(self, symbol: str) -> Decimal | None:
        """ATR-14 from the last stored Bar row for *symbol*."""
        with get_session() as session:
            stmt = (
                select(Bar)
                .where(Bar.symbol == symbol.upper())
                .order_by(Bar.trading_date.desc())  # type: ignore[attr-defined]
                .limit(1)
            )
            bar = session.exec(stmt).first()

        # Bar doesn't store ATR — compute from recent close prices
        if bar is None:
            return None
        return _compute_atr_from_db(symbol.upper(), self._ref_date)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_from_t212(self, client) -> tuple[Decimal, dict[str, Decimal], dict[str, str]]:
        """Load cash + positions from T212; return (nav, position_values, db_sectors)."""
        nav = Decimal("0")
        try:
            cash_info = client.get_cash()
            # `total` is the account NAV — free cash plus the market value of
            # every open position. Adding position values on top of it would
            # double-count the invested portion.
            nav = cash_info.total
        except Exception:
            logger.exception("Failed to fetch T212 cash")

        position_values: dict[str, Decimal] = {}
        db_sectors: dict[str, str] = {}

        try:
            positions = client.get_positions()
            # Position prices are quoted in the instrument's own currency
            # (USD, GBX pence, …); convert to the GBP account currency so the
            # values are comparable with NAV in the risk rails.
            currencies: dict[str, str] = {}
            try:
                currencies = client.get_instruments()
            except Exception:
                logger.warning(
                    "T212 instrument metadata unavailable — position values not currency-normalised"
                )
            fx_rates = get_gbp_rates() if currencies else {}
            for pos in positions:
                price = to_gbp(pos.current_price, currencies.get(pos.ticker, ""), fx_rates)
                position_values[pos.ticker.upper()] = price * pos.quantity
        except Exception:
            logger.exception("Failed to fetch T212 positions")

        # Sector fallback from DB Position table
        with get_session() as session:
            db_positions = session.exec(select(Position)).all()
            for p in db_positions:
                if p.sector:
                    db_sectors[p.symbol.upper()] = p.sector

        return nav, position_values, db_sectors


def _trading_days_between(start: date, end: date) -> int:
    """Approximate trading days between start and end (inclusive of end, not start)."""
    if end <= start:
        return 0
    days = 0
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            days += 1
        current += timedelta(days=1)
    return days


def _compute_atr_from_db(symbol: str, ref_date: date, period: int = 14) -> Decimal | None:
    """Compute ATR-14 from the last `period+1` bars stored in the DB."""
    with get_session() as session:
        stmt = (
            select(Bar)
            .where(Bar.symbol == symbol, Bar.trading_date <= ref_date)
            .order_by(Bar.trading_date.desc())  # type: ignore[attr-defined]
            .limit(period + 1)
        )
        bars = list(reversed(session.exec(stmt).all()))

    if len(bars) < 2:
        return None

    true_ranges: list[Decimal] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        high = bars[i].high
        low = bars[i].low
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if not true_ranges:
        return None

    return sum(true_ranges, Decimal("0")) / len(true_ranges)
