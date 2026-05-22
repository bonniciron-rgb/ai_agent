"""Hard risk limits enforced before any order reaches the broker.

Five rules — all must pass for a proposal to be allowed:

1. Position cap    — ticker notional ≤ 5 % of portfolio NAV
2. ATR stop        — stop_price present and >= limit_price - 2xATR
3. Daily turnover  — cumulative order notional today ≤ 20 % of NAV
4. Sector cap      — sector notional ≤ 30 % of NAV
5. Cooldown        — no re-entry within 5 trading days after a sell

Usage::

    checker = RiskChecker(portfolio)
    result = checker.check(proposal)
    if result.allowed:
        submit(proposal)
    else:
        log(result.reason)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POSITION_CAP_PCT: Decimal = Decimal("0.05")  # 5 %
ATR_STOP_MULTIPLIER: Decimal = Decimal("2")  # 2x ATR
DAILY_TURNOVER_CAP_PCT: Decimal = Decimal("0.20")  # 20 %
SECTOR_CAP_PCT: Decimal = Decimal("0.30")  # 30 %
COOLDOWN_DAYS: int = 5


# ---------------------------------------------------------------------------
# Portfolio snapshot protocol
# ---------------------------------------------------------------------------


class PortfolioSnapshot(Protocol):
    """Read-only view of portfolio state needed by the risk checker."""

    @property
    def nav(self) -> Decimal:
        """Total portfolio net-asset value."""
        ...

    def position_value(self, symbol: str) -> Decimal:
        """Current market value held in *symbol* (0 if not held)."""
        ...

    def sector_value(self, sector: str) -> Decimal:
        """Current market value of all positions in *sector*."""
        ...

    def symbol_sector(self, symbol: str) -> str | None:
        """Return the sector string for *symbol*, or None if unknown."""
        ...

    def daily_turnover(self) -> Decimal:
        """Total notional of orders already placed today."""
        ...

    def days_since_last_sell(self, symbol: str) -> int | None:
        """Trading days since the last sell on *symbol* (None = never sold)."""
        ...

    def atr(self, symbol: str) -> Decimal | None:
        """Most-recent 14-day ATR for *symbol*, or None if unavailable."""
        ...


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RailResult:
    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


PASS = RailResult(allowed=True)


def _fail(msg: str) -> RailResult:
    return RailResult(allowed=False, reason=msg)


# ---------------------------------------------------------------------------
# Individual rail functions
# ---------------------------------------------------------------------------


def check_position_cap(
    symbol: str,
    order_notional: Decimal,
    portfolio: PortfolioSnapshot,
) -> RailResult:
    """Ticker notional after fill must not exceed POSITION_CAP_PCT of NAV."""
    if portfolio.nav <= 0:
        return _fail("NAV is zero or negative")
    current = portfolio.position_value(symbol)
    projected = current + order_notional
    cap = portfolio.nav * POSITION_CAP_PCT
    if projected > cap:
        pct = (projected / portfolio.nav * 100).quantize(Decimal("0.1"))
        return _fail(
            f"Position cap: {symbol} would be {pct}% of NAV (limit {int(POSITION_CAP_PCT * 100)}%)"
        )
    return PASS


def check_atr_stop(
    symbol: str,
    limit_price: Decimal,
    stop_price: Decimal | None,
    portfolio: PortfolioSnapshot,
) -> RailResult:
    """Stop must be present and at least ATR_STOP_MULTIPLIER x ATR below limit."""
    if stop_price is None:
        return _fail(f"ATR stop: no stop_price supplied for {symbol}")
    atr = portfolio.atr(symbol)
    if atr is None or atr <= 0:
        # Can't validate without ATR data — let through with a warning in reason
        return RailResult(allowed=True, reason=f"ATR stop: ATR unavailable for {symbol}, skipped")
    min_stop = limit_price - ATR_STOP_MULTIPLIER * atr
    if stop_price < min_stop:
        return _fail(
            f"ATR stop: stop ${stop_price} < min ${min_stop:.2f} "
            f"(limit ${limit_price} - {ATR_STOP_MULTIPLIER}x ATR ${atr:.2f})"
        )
    return PASS


def check_daily_turnover(
    order_notional: Decimal,
    portfolio: PortfolioSnapshot,
) -> RailResult:
    """Cumulative order notional today must not exceed DAILY_TURNOVER_CAP_PCT of NAV."""
    if portfolio.nav <= 0:
        return _fail("NAV is zero or negative")
    projected = portfolio.daily_turnover() + order_notional
    cap = portfolio.nav * DAILY_TURNOVER_CAP_PCT
    if projected > cap:
        pct = (projected / portfolio.nav * 100).quantize(Decimal("0.1"))
        return _fail(
            f"Daily turnover: {pct}% of NAV today (limit {int(DAILY_TURNOVER_CAP_PCT * 100)}%)"
        )
    return PASS


def check_sector_cap(
    symbol: str,
    order_notional: Decimal,
    portfolio: PortfolioSnapshot,
) -> RailResult:
    """Sector notional after fill must not exceed SECTOR_CAP_PCT of NAV."""
    sector = portfolio.symbol_sector(symbol)
    if sector is None:
        # Unknown sector — let through, can't validate
        return RailResult(allowed=True, reason=f"Sector cap: sector unknown for {symbol}, skipped")
    if portfolio.nav <= 0:
        return _fail("NAV is zero or negative")
    current_sector = portfolio.sector_value(sector)
    projected = current_sector + order_notional
    cap = portfolio.nav * SECTOR_CAP_PCT
    if projected > cap:
        pct = (projected / portfolio.nav * 100).quantize(Decimal("0.1"))
        return _fail(
            f"Sector cap: {sector} would be {pct}% of NAV (limit {int(SECTOR_CAP_PCT * 100)}%)"
        )
    return PASS


def check_cooldown(symbol: str, portfolio: PortfolioSnapshot) -> RailResult:
    """Reject re-entry if last sell was within COOLDOWN_DAYS trading days."""
    days = portfolio.days_since_last_sell(symbol)
    if days is not None and days < COOLDOWN_DAYS:
        return _fail(f"Cooldown: {symbol} sold {days} day(s) ago (cooldown={COOLDOWN_DAYS} days)")
    return PASS


# ---------------------------------------------------------------------------
# Aggregated checker
# ---------------------------------------------------------------------------


@dataclass
class RiskChecker:
    """Run all five rails against a proposal.

    Parameters
    ----------
    portfolio:
        Live or test PortfolioSnapshot.
    halt:
        When True, every proposal is rejected immediately (kill-switch state).
    usd_to_gbp:
        Multiplier converting a USD price to GBP. Proposals are US-listed, so
        limit prices are in USD while NAV is in GBP; default 1 (no conversion)
        keeps same-currency callers and tests unaffected.
    warnings:
        Accumulated non-blocking advisory messages from the last check.
    """

    portfolio: PortfolioSnapshot
    halt: bool = False
    usd_to_gbp: Decimal = Decimal(1)
    warnings: list[str] = field(default_factory=list)

    def check(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        limit_price: Decimal,
        stop_price: Decimal | None = None,
    ) -> RailResult:
        """Return a RailResult.  Populates self.warnings with advisory messages."""
        self.warnings = []

        if self.halt:
            return _fail("Kill switch: trading is halted")

        # Only BUY proposals go through all rails; SELL proposals skip position/sector caps
        # limit_price is in the instrument currency (USD); NAV is GBP.
        order_notional = limit_price * quantity * self.usd_to_gbp

        if side.lower() == "buy":
            if stop_price is None:
                return _fail(f"{symbol}: every buy must define a stop_price")
            for result in (
                check_position_cap(symbol, order_notional, self.portfolio),
                check_atr_stop(symbol, limit_price, stop_price, self.portfolio),
                check_daily_turnover(order_notional, self.portfolio),
                check_sector_cap(symbol, order_notional, self.portfolio),
                check_cooldown(symbol, self.portfolio),
            ):
                if not result.allowed:
                    return result
                if result.reason:  # allowed but has advisory text
                    self.warnings.append(result.reason)
        else:  # sell (exit)
            # A stop is an entry-side control; an exit is not gated by one. The
            # agent omits stop_price on full exits by design (see prompts.py),
            # so only the daily-turnover cap applies here.
            turnover = check_daily_turnover(order_notional, self.portfolio)
            if not turnover.allowed:
                return turnover
            if turnover.reason:
                self.warnings.append(turnover.reason)

        return PASS
