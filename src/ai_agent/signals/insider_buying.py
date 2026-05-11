"""A3: Insider Buying (Form 4) Signal — fourth real alpha signal through C1 harness.

Goes long when a configurable minimum number of distinct insiders (officers or
directors) have made open-market purchases totalling at least ``min_total_value_usd``
within a rolling ``lookback_days`` window ending at the current bar's date.

Academic basis: Cohen, Malloy, Pomorski (2012) "Decoding Inside Information" (Journal
of Finance) demonstrated that officer/director open-market purchases strongly predict
6-12 month excess returns.  Outside-director purchases are especially informative.
The effect survives transaction-cost adjustment and is robust across market cycles.

Bullish filter:
  - ``transaction_code == "P"`` (open-market purchase only; not option exercise/award/gift)
  - ``direct_or_indirect_ownership == "D"`` (direct ownership; exclude nominee vehicles)
  - ``is_officer OR is_director`` (informed insiders; 10% owners excluded)

Long-only.  No short leg on insider selling (reserved for a future variant).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ai_agent.signals.base import SignalContext, SignalResult

_DEFAULT_MIN_BUY_COUNT = 2
_DEFAULT_MIN_TOTAL_VALUE_USD = 50_000.0
_DEFAULT_LOOKBACK_DAYS = 90


@dataclass
class InsiderBuy:
    """A single Form 4 insider purchase transaction.

    Parameters
    ----------
    transaction_date:
        The date the transaction was executed (not the filing date).
    cik:
        SEC CIK of the reporting person (filing insider), as a string.
    transaction_shares:
        Number of shares purchased.  Positive for buys.
    transaction_price:
        Price per share at time of transaction.
    transaction_value_usd:
        Total value of the transaction (``transaction_shares * transaction_price``).
        Callers are responsible for computing this; the signal trusts the value.
    transaction_code:
        SEC Form 4 transaction code.  ``"P"`` = open-market purchase.
    direct_or_indirect_ownership:
        ``"D"`` for direct ownership; ``"I"`` for indirect (e.g., via trust or LLC).
    is_officer:
        Whether the reporting person is a company officer.
    is_director:
        Whether the reporting person is a member of the board of directors.
    is_ten_percent_owner:
        Whether the reporting person holds ≥10% of the class.
    """

    transaction_date: date
    cik: str
    transaction_shares: int
    transaction_price: float
    transaction_value_usd: float
    transaction_code: str
    direct_or_indirect_ownership: str
    is_officer: bool
    is_director: bool
    is_ten_percent_owner: bool


class InsiderBuyingSignal:
    """Long when multiple insiders make qualifying open-market purchases within a window.

    Parameters
    ----------
    insider_events:
        Pre-fetched Form 4 transaction history keyed by symbol.  Each value is a list of
        :class:`InsiderBuy` objects in chronological order (oldest first).  The runner /
        test setup is responsible for populating this dict; the signal performs no I/O.
    min_buy_count:
        Minimum number of *distinct* insiders (by CIK) that must have qualifying
        purchases within the lookback window.  Default 2.
    min_total_value_usd:
        Combined USD value of all qualifying purchases within the window must reach this
        threshold.  Default $50,000.
    lookback_days:
        Calendar days before the bar's ``as_of`` date within which purchases are
        considered current.  Purchases older than this window are ignored.  Default 90.
    """

    name = "insider_buying"
    version = "0.1.0"

    def __init__(
        self,
        insider_events: dict[str, list[InsiderBuy]] | None = None,
        min_buy_count: int = _DEFAULT_MIN_BUY_COUNT,
        min_total_value_usd: float = _DEFAULT_MIN_TOTAL_VALUE_USD,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self.insider_events: dict[str, list[InsiderBuy]] = insider_events or {}
        self.min_buy_count = min_buy_count
        self.min_total_value_usd = min_total_value_usd
        self.lookback_days = lookback_days

    def compute(self, ctx: SignalContext) -> SignalResult:
        """Return ``score=1.0`` when qualifying insider buying condition is met, ``0.0`` otherwise."""
        events = self.insider_events.get(ctx.symbol)
        if not events:
            return SignalResult(score=0.0, notes=["no insider buying data for symbol"])

        as_of = ctx.as_of

        # Filter to qualifying events within the lookback window.
        qualifying: list[InsiderBuy] = []
        for ev in events:
            # Must be within the lookback window (not older than lookback_days).
            days_since = (as_of - ev.transaction_date).days
            if days_since < 0:
                # Future transaction relative to bar date — skip.
                continue
            if days_since > self.lookback_days:
                continue

            # Must be an open-market purchase (transaction code "P").
            if ev.transaction_code != "P":
                continue

            # Must be direct ownership (not through a vehicle/trust).
            if ev.direct_or_indirect_ownership != "D":
                continue

            # Must be an officer or director; skip pure 10% owners.
            if not (ev.is_officer or ev.is_director):
                continue

            qualifying.append(ev)

        if not qualifying:
            return SignalResult(
                score=0.0,
                notes=[
                    f"no qualifying officer/director open-market purchases "
                    f"within {self.lookback_days}d lookback"
                ],
            )

        # Count distinct insiders (by CIK) and total value.
        distinct_ciks: set[str] = {ev.cik for ev in qualifying}
        total_value = sum(ev.transaction_value_usd for ev in qualifying)

        if len(distinct_ciks) < self.min_buy_count:
            return SignalResult(
                score=0.0,
                notes=[
                    f"{ctx.symbol} only {len(distinct_ciks)} distinct insider(s) bought "
                    f"within {self.lookback_days}d — need {self.min_buy_count} "
                    f"(total value ${total_value:,.0f})"
                ],
            )

        if total_value < self.min_total_value_usd:
            return SignalResult(
                score=0.0,
                notes=[
                    f"{ctx.symbol} combined purchase value ${total_value:,.0f} "
                    f"< threshold ${self.min_total_value_usd:,.0f} "
                    f"({len(distinct_ciks)} distinct insider(s), {self.lookback_days}d window)"
                ],
            )

        return SignalResult(
            score=1.0,
            notes=[
                f"{ctx.symbol} {len(distinct_ciks)} distinct insider(s) purchased "
                f"${total_value:,.0f} combined within {self.lookback_days}d "
                f"(>= {self.min_buy_count} buyers, >= ${self.min_total_value_usd:,.0f} threshold)"
            ],
        )
