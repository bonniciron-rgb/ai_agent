"""Production exposure-manager job: compute & persist the daily SPY tilt.

This is the *live* counterpart to ``scripts/run_all_backtests.py``'s
``SPY_tilt_50_100`` run. It builds the same CompositeFactorSignal (A1 sector RS
+ A2 PEAD + B2 analyst-revisions, equal-weight) over the same 11-symbol
universe, evaluates it on the latest bar of each symbol, maps the
universe-average score to a target SPY allocation (50-100% band by default,
``score_ceiling=0.30``), and writes an :class:`ExposureSnapshot` row.

``SECTOR_MAP`` is the single source of truth for the exposure universe;
``scripts/run_all_backtests.py`` imports it from here so the backtest and the
live tilt can never disagree about which symbols are in play.

Run::

    python -m ai_agent.exposure.job
    # or
    python scripts/tilt_snapshot.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta

import pandas as pd

from ai_agent.db.engine import get_engine, init_schema
from ai_agent.db.models import ExposureSnapshot
from ai_agent.exposure.tilt import TiltSnapshot, compute_tilt_snapshot
from ai_agent.signals.analyst_revisions import AnalystRevisionMomentumSignal, RecommendationSnapshot
from ai_agent.signals.composite import CompositeFactorSignal
from ai_agent.signals.pead import EarningsEvent, PostEarningsDriftSignal
from ai_agent.signals.sector_rs import SectorRelativeStrengthSignal

logger = logging.getLogger(__name__)

# v4 exposure universe (see etheratrading.md Batch 19): tech / financials /
# energy / momentum-consumer-discretionary. Defensives + pharma were dropped
# because A1's relative-strength logic mean-reverts on them.
SECTOR_MAP: dict[str, str] = {
    "AAPL": "XLK",
    "MSFT": "XLK",
    "GOOGL": "XLK",
    "JPM": "XLF",
    "BAC": "XLF",
    "GS": "XLF",
    "XOM": "XLE",
    "CVX": "XLE",
    "AMZN": "XLY",
    "HD": "XLY",
    "TSLA": "XLY",
}
UNIVERSE: list[str] = sorted(SECTOR_MAP.keys())
ETFS: list[str] = sorted(set(SECTOR_MAP.values()))
BENCHMARK = "SPY"

# Tilt config — must match scripts/run_all_backtests.py's SPY_tilt run.
MIN_ALLOC = 0.5
MAX_ALLOC = 1.0
SCORE_CEILING = 0.30
WARMUP_BARS = 50


def build_composite_signal(
    sector_prices: dict[str, pd.Series],
    *,
    earnings_by_sym: dict[str, list[EarningsEvent]] | None = None,
    recs_by_sym: dict[str, list[RecommendationSnapshot]] | None = None,
) -> CompositeFactorSignal:
    """Build the equal-weight A1+A2+B2 composite used by the exposure manager.

    ``earnings_by_sym`` / ``recs_by_sym`` are optional — when omitted, A2 and B2
    simply return 0.0 (no data), which is their behaviour on ~98% of bars in the
    backtest anyway, so an A1-only-data snapshot is a close approximation.
    """
    a1 = SectorRelativeStrengthSignal(
        sector_map=SECTOR_MAP,
        sector_prices=sector_prices,
        lookback=20,
        threshold=0.03,
    )
    a2 = PostEarningsDriftSignal(earnings_events=earnings_by_sym or {}, surprise_threshold=0.03)
    b2 = AnalystRevisionMomentumSignal(recommendations=recs_by_sym or {})
    return CompositeFactorSignal(sub_signals=[a1, a2, b2], name_suffix="equal_weight")


def make_snapshot(
    universe_bars: dict[str, pd.DataFrame],
    sector_prices: dict[str, pd.Series],
    *,
    earnings_by_sym: dict[str, list[EarningsEvent]] | None = None,
    recs_by_sym: dict[str, list[RecommendationSnapshot]] | None = None,
    as_of: date | None = None,
) -> TiltSnapshot:
    """Compute the current tilt snapshot (pure — no I/O, no persistence)."""
    composite = build_composite_signal(
        sector_prices, earnings_by_sym=earnings_by_sym, recs_by_sym=recs_by_sym
    )
    return compute_tilt_snapshot(
        composite,
        universe_bars,
        as_of=as_of,
        min_alloc=MIN_ALLOC,
        max_alloc=MAX_ALLOC,
        score_ceiling=SCORE_CEILING,
        warmup_bars=WARMUP_BARS,
    )


def persist_snapshot(snap: TiltSnapshot, *, engine=None) -> ExposureSnapshot:
    """Upsert an ExposureSnapshot row keyed by ``as_of``."""
    from sqlmodel import Session, select

    eng = engine or get_engine()
    with Session(eng) as session:
        existing = session.exec(
            select(ExposureSnapshot).where(ExposureSnapshot.as_of == snap.as_of)
        ).first()
        if existing is not None:
            existing.composite_score = snap.composite_score
            existing.target_allocation = snap.target_allocation
            existing.n_symbols = snap.n_symbols
            existing.score_ceiling = snap.score_ceiling
            existing.per_symbol_scores_json = json.dumps(snap.per_symbol_scores)
            row = existing
        else:
            row = ExposureSnapshot(
                as_of=snap.as_of,
                composite_score=snap.composite_score,
                target_allocation=snap.target_allocation,
                n_symbols=snap.n_symbols,
                score_ceiling=snap.score_ceiling,
                per_symbol_scores_json=json.dumps(snap.per_symbol_scores),
            )
            session.add(row)
        session.commit()
        session.refresh(row)
        return row


def latest_snapshot(*, engine=None) -> ExposureSnapshot | None:
    """Return the most recent persisted ExposureSnapshot, or None."""
    from sqlmodel import Session, select

    eng = engine or get_engine()
    with Session(eng) as session:
        return session.exec(
            select(ExposureSnapshot).order_by(ExposureSnapshot.as_of.desc())  # type: ignore[attr-defined]
        ).first()


# ---------------------------------------------------------------------------
# CLI — fetches prices via yfinance, builds sector_prices, persists a snapshot.
# ---------------------------------------------------------------------------


def _fetch_recent_bars(tickers: list[str], lookback_days: int = 400) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    end = date.today()
    start = end - timedelta(days=lookback_days)
    raw = yf.download(
        tickers,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    out: dict[str, pd.DataFrame] = {}
    for sym in tickers:
        try:
            sub = raw.xs(sym.upper(), axis=1, level=1) if raw.columns.nlevels > 1 else raw.copy()
            sub = sub.rename(columns=str.lower)
            cols = [c for c in ["open", "high", "low", "close", "volume"] if c in sub.columns]
            sub = sub[cols].dropna()
            if not sub.empty:
                out[sym.upper()] = sub
        except Exception as exc:
            logger.warning("yfinance extract failed for %s: %s", sym, exc)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute & persist the daily SPY exposure tilt.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute and log without writing to the DB"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    all_tickers = sorted(set(UNIVERSE) | set(ETFS) | {BENCHMARK})
    bars = _fetch_recent_bars(all_tickers)
    universe_bars = {s: bars[s] for s in UNIVERSE if s in bars}
    sector_prices: dict[str, pd.Series] = {}
    for etf in [*ETFS, BENCHMARK]:
        if etf in bars and not bars[etf].empty:
            ser = bars[etf]["close"].copy()
            ser.index = pd.to_datetime(ser.index).date
            sector_prices[etf] = ser

    snap = make_snapshot(universe_bars, sector_prices)
    logger.info(
        "Exposure tilt: as_of=%s alloc=%d%% composite=%+.3f n_symbols=%d",
        snap.as_of,
        snap.allocation_pct,
        snap.composite_score,
        snap.n_symbols,
    )
    if args.dry_run:
        return 0

    init_schema()
    row = persist_snapshot(snap)
    logger.info("ExposureSnapshot saved: id=%s as_of=%s", row.id, row.as_of)
    return 0


if __name__ == "__main__":
    sys.exit(main())
