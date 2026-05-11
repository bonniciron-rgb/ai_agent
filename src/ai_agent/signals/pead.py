"""A2: Post-Earnings Drift (PEAD) Signal — second real alpha signal through C1 harness.

Goes long when a stock has posted a positive earnings surprise above a configurable
threshold within the lookback window, and holds for a configurable number of calendar
days after the announcement.

Academic basis: Bernard & Thomas (1989, 1990) showed that stocks drift in the direction
of their earnings surprise for approximately 30-60 days post-announcement.  PEAD is one
of the most replicated anomalies in empirical finance.

Long-only.  No short leg on negative surprises (reserved for a future variant).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ai_agent.signals.base import SignalContext, SignalResult

_DEFAULT_SURPRISE_THRESHOLD = 0.05  # 5% beat required
_DEFAULT_HOLDING_WINDOW = 30  # calendar days
_DEFAULT_LOOKBACK_WINDOW = 60  # calendar days


@dataclass
class EarningsEvent:
    """A single historical earnings announcement for one symbol.

    Parameters
    ----------
    announcement_date:
        The date the earnings were announced (market-date, not the fiscal period end).
    actual_eps:
        Reported EPS for the period.
    consensus_eps:
        Analyst consensus EPS estimate at time of announcement.
    surprise_pct:
        Pre-computed relative surprise: ``(actual_eps - consensus_eps) / abs(consensus_eps)``.
        Callers are responsible for computing this; the signal trusts the value.
    """

    announcement_date: date
    actual_eps: float
    consensus_eps: float
    surprise_pct: float


class PostEarningsDriftSignal:
    """Long when a recent positive earnings surprise exceeds the threshold.

    Parameters
    ----------
    earnings_events:
        Pre-fetched earnings history keyed by symbol.  Each value is a list of
        :class:`EarningsEvent` objects in *any* order; the signal finds the most
        recent qualifying event itself.  The runner / test setup is responsible
        for populating this dict; the signal performs no I/O.
    surprise_threshold:
        Minimum relative EPS beat required to go long.  Default 0.05 (= 5%).
    holding_window_days:
        Maximum calendar days *after* the announcement to hold a long position.
        If the bar date exceeds ``announcement_date + holding_window_days`` the
        signal goes flat even if the surprise was large.  Default 30.
    lookback_window_days:
        How far back (calendar days before the bar's date) to search for a
        qualifying earnings announcement.  Events older than this window are
        ignored.  Default 60.
    """

    name = "post_earnings_drift"
    version = "0.1.0"

    def __init__(
        self,
        earnings_events: dict[str, list[EarningsEvent]] | None = None,
        surprise_threshold: float = _DEFAULT_SURPRISE_THRESHOLD,
        holding_window_days: int = _DEFAULT_HOLDING_WINDOW,
        lookback_window_days: int = _DEFAULT_LOOKBACK_WINDOW,
    ) -> None:
        self.earnings_events: dict[str, list[EarningsEvent]] = earnings_events or {}
        self.surprise_threshold = surprise_threshold
        self.holding_window_days = holding_window_days
        self.lookback_window_days = lookback_window_days

    def compute(self, ctx: SignalContext) -> SignalResult:
        """Return ``score=1.0`` when inside a PEAD window, ``0.0`` otherwise."""
        events = self.earnings_events.get(ctx.symbol)
        if not events:
            return SignalResult(score=0.0, notes=["no earnings data for symbol"])

        as_of = ctx.as_of

        # Search all events; pick the best (highest surprise) qualifying one.
        best: EarningsEvent | None = None
        for ev in events:
            ann = ev.announcement_date

            # Must be within the lookback window (not older than lookback_window_days).
            days_since = (as_of - ann).days
            if days_since < 0:
                # Future announcement relative to bar date — skip.
                continue
            if days_since > self.lookback_window_days:
                continue

            # Must still be within the holding window.
            if days_since > self.holding_window_days:
                continue

            # Must meet the surprise threshold.
            if ev.surprise_pct < self.surprise_threshold:
                continue

            if best is None or ev.surprise_pct > best.surprise_pct:
                best = ev

        if best is None:
            return SignalResult(
                score=0.0,
                notes=[
                    f"no qualifying earnings surprise >= {self.surprise_threshold * 100:.1f}% "
                    f"within [{self.holding_window_days}d holding / {self.lookback_window_days}d lookback]"
                ],
            )

        days_since_best = (as_of - best.announcement_date).days
        return SignalResult(
            score=1.0,
            notes=[
                f"{ctx.symbol} earnings {best.announcement_date.isoformat()} "
                f"surprise {best.surprise_pct * 100:.2f}% "
                f">= threshold {self.surprise_threshold * 100:.1f}% "
                f"({days_since_best}d ago, holding window {self.holding_window_days}d)"
            ],
        )
