"""B2: Analyst Estimate Revision Momentum Signal — third real alpha signal through C1 harness.

Goes long when the analyst recommendation distribution has shifted positively for
``min_consecutive_months`` consecutive months (strictly improving bullish score) within
the most recent ``lookback_months`` months.  Long-only; flat otherwise.

Academic basis: Hawkins et al. and related literature demonstrate that stocks with
consistent upward analyst revisions outperform for 3-12 months post-revision.  The
effect is strongest when the upgrade streak is recent and sustained.

Long-only.  No short leg on deteriorating analyst sentiment (reserved for a future variant).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ai_agent.signals.base import SignalContext, SignalResult

_DEFAULT_MIN_CONSECUTIVE_MONTHS = 3
_DEFAULT_LOOKBACK_MONTHS = 6


@dataclass
class RecommendationSnapshot:
    """A single monthly analyst recommendation distribution for one symbol.

    Parameters
    ----------
    period:
        The month-end date for this recommendation snapshot (Finnhub returns
        YYYY-MM-DD strings; typically the last day of the reported month).
    strong_buy:
        Number of analysts with a Strong Buy rating.
    buy:
        Number of analysts with a Buy rating.
    hold:
        Number of analysts with a Hold rating.
    sell:
        Number of analysts with a Sell rating.
    strong_sell:
        Number of analysts with a Strong Sell rating.
    """

    period: date
    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int

    @property
    def bullish_score(self) -> float:
        """Weighted sentiment score normalised by total analyst count.

        Formula::

            (strongBuy * 2 + buy * 1 - sell * 1 - strongSell * 2) / total_analysts

        Returns 0.0 when there are no analysts covering the stock.
        """
        total = self.strong_buy + self.buy + self.hold + self.sell + self.strong_sell
        if total == 0:
            return 0.0
        return (self.strong_buy * 2 + self.buy * 1 - self.sell * 1 - self.strong_sell * 2) / total


class AnalystRevisionMomentumSignal:
    """Long when analyst recommendation distribution improves for N consecutive months.

    Parameters
    ----------
    recommendations:
        Pre-fetched recommendation history keyed by symbol.  Each value is a list of
        :class:`RecommendationSnapshot` objects in *chronological* order (oldest first).
        The runner / test setup is responsible for populating this dict; the signal
        performs no I/O.
    min_consecutive_months:
        Number of consecutive months of strictly improving bullish score required to
        go long.  Default 3.
    lookback_months:
        How many months back from the most recent snapshot to search for the streak.
        Streaks whose most recent month falls outside this window are ignored.
        Default 6.
    """

    name = "analyst_revision_momentum"
    version = "0.1.0"

    def __init__(
        self,
        recommendations: dict[str, list[RecommendationSnapshot]] | None = None,
        min_consecutive_months: int = _DEFAULT_MIN_CONSECUTIVE_MONTHS,
        lookback_months: int = _DEFAULT_LOOKBACK_MONTHS,
    ) -> None:
        self.recommendations: dict[str, list[RecommendationSnapshot]] = recommendations or {}
        self.min_consecutive_months = min_consecutive_months
        self.lookback_months = lookback_months

    def compute(self, ctx: SignalContext) -> SignalResult:
        """Return ``score=1.0`` when a qualifying upgrade streak is active, ``0.0`` otherwise."""
        snapshots = self.recommendations.get(ctx.symbol)
        if not snapshots:
            return SignalResult(score=0.0, notes=["no recommendation data for symbol"])

        as_of = ctx.as_of

        # Filter to snapshots within the lookback window (period <= as_of).
        # Finnhub periods are month-end dates; exclude future periods.
        lookback_cutoff = _subtract_months(as_of, self.lookback_months)
        in_window = [s for s in snapshots if lookback_cutoff <= s.period <= as_of]

        if len(in_window) < self.min_consecutive_months:
            return SignalResult(
                score=0.0,
                notes=[
                    f"only {len(in_window)} snapshot(s) in lookback window "
                    f"({self.lookback_months}mo), need {self.min_consecutive_months}"
                ],
            )

        # Snapshots are expected chronological; ensure order.
        ordered = sorted(in_window, key=lambda s: s.period)

        # Find the longest trailing streak of strictly increasing bullish_score
        # ending at the most recent snapshot in the window.
        streak = 1
        for i in range(len(ordered) - 1, 0, -1):
            if ordered[i].bullish_score > ordered[i - 1].bullish_score:
                streak += 1
            else:
                break

        streak_end = ordered[-1]

        if streak < self.min_consecutive_months:
            return SignalResult(
                score=0.0,
                notes=[
                    f"{ctx.symbol} trailing streak {streak} month(s) < "
                    f"required {self.min_consecutive_months} "
                    f"(latest period {streak_end.period.isoformat()}, "
                    f"bullish_score {streak_end.bullish_score:.3f})"
                ],
            )

        return SignalResult(
            score=1.0,
            notes=[
                f"{ctx.symbol} analyst upgrade streak {streak} consecutive month(s) "
                f">= {self.min_consecutive_months} required "
                f"(streak ended {streak_end.period.isoformat()}, "
                f"bullish_score {streak_end.bullish_score:.3f})"
            ],
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _subtract_months(d: date, months: int) -> date:
    """Return the date *months* calendar months before *d* (clamped to month end)."""
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    # Clamp day to the last valid day of the target month.
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))
