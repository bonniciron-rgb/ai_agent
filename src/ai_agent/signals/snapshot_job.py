"""Compute & persist per-symbol quant-signal snapshots for the trading agent.

Runs daily (``scripts/compute_signals.py`` +
``.github/workflows/compute-signals.yml``) BEFORE the trade loop. For each
watchlist symbol it evaluates four event/positioning signals using live data:

  * post_earnings_drift       — Finnhub earnings surprises
  * analyst_revision_momentum — Finnhub recommendation trends
  * insider_buying            — SEC EDGAR Form 4
  * short_interest_momentum   — yfinance short %% of float

and writes one :class:`SignalSnapshot` row per symbol. The agent's
``get_quant_signals`` tool reads the latest snapshot, which keeps slow,
rate-limited API calls out of the latency-sensitive decision loop AND leaves a
historical signal record the feedback loop (next PR) can correlate against
trade outcomes.

Sector relative strength (A1) is intentionally excluded for now: it needs
sector-ETF bars ingested into the ``Bar`` table, which the daily loop does not
do yet. That is a follow-up.

The live data fetches reuse the resilient ``_inject_*`` helpers in
``signals.runner`` — each degrades to a zero/empty contribution when its source
is unavailable, so a single dead API never aborts the run.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import ai_agent.db.engine as _engine
from ai_agent.db.models import SignalSnapshot
from ai_agent.loop.bar_store import bars_from_db
from ai_agent.signals.analyst_revisions import AnalystRevisionMomentumSignal
from ai_agent.signals.base import Signal, SignalContext, SignalResult
from ai_agent.signals.insider_buying import InsiderBuyingSignal
from ai_agent.signals.pead import PostEarningsDriftSignal
from ai_agent.signals.runner import (
    _bars_to_dataframe,
    _inject_earnings_events,
    _inject_insider_events,
    _inject_recommendations,
    _inject_short_interest,
)
from ai_agent.signals.sector_rs import SectorRelativeStrengthSignal
from ai_agent.signals.short_interest import ShortInterestMomentumSignal

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# short_interest needs lookback_days+1 bars; 60 is comfortably above all four.
WARMUP_BARS = 60
DAYS_BACK = 400

# SPDR sector ETFs covering every sector string used in config/watchlist.yaml.
# Symbols whose sector is missing or unmapped fall back to SPY (whole market).
SECTOR_TO_ETF: dict[str, str] = {
    "technology": "XLK",
    "communication_services": "XLC",
    "consumer_discretionary": "XLY",
    "consumer_staples": "XLP",
    "healthcare": "XLV",
    "financials": "XLF",
    "industrials": "XLI",
    "energy": "XLE",
    "utilities": "XLU",
    "materials": "XLB",
}
DEFAULT_ETF = "SPY"


def _build_sector_map(watchlist) -> dict[str, str]:
    """Map ``{SYMBOL: ETF}`` from a Watchlist's per-entry sector strings.

    Symbols with an unknown / missing sector get :data:`DEFAULT_ETF` (SPY) so
    SectorRS still has an opinion (stock vs. whole market) rather than going
    flat by default.
    """
    return {
        entry.symbol.upper(): SECTOR_TO_ETF.get(entry.sector or "", DEFAULT_ETF)
        for entry in watchlist.entries
    }


def _fetch_sector_etf_prices(etfs: list[str], *, days_back: int = DAYS_BACK) -> dict:
    """Pull closing-price series for sector ETFs via yfinance.

    Reuses the same fetcher that ``exposure/job.py`` uses live, so the snapshot
    job doesn't need sector ETFs to be ingested into the ``Bar`` table — a
    deliberate trade-off to keep SectorRS wiring contained.

    Returns ``{ETF: pd.Series}`` keyed by ticker with a date-typed index
    matching ``SignalContext.bars.index``. Resilient: a network failure logs
    and returns ``{}``, after which SectorRS degrades to ``score=0`` with a
    clear "no sector prices" note.
    """
    if not etfs:
        return {}
    try:
        import pandas as pd

        from ai_agent.exposure.job import _fetch_recent_bars
    except ImportError:
        logger.warning("yfinance / pandas missing; SectorRS will be flat")
        return {}
    try:
        bars = _fetch_recent_bars(sorted(set(etfs)), lookback_days=days_back)
    except Exception:
        logger.exception("yfinance ETF fetch failed; SectorRS will be flat")
        return {}
    out: dict = {}
    for etf, df in bars.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        ser = df["close"].copy()
        ser.index = pd.to_datetime(ser.index).date
        out[etf.upper()] = ser
    return out


def build_signals(
    *,
    sector_map: dict[str, str] | None = None,
    sector_prices: dict | None = None,
) -> list[Signal]:
    """The event/positioning signals, freshly constructed (empty data).

    ``sector_map`` enables SectorRS; without it, SectorRS is omitted (the
    signal needs to know which ETF to compare each symbol to).
    """
    sigs: list[Signal] = [
        PostEarningsDriftSignal(),
        AnalystRevisionMomentumSignal(),
        InsiderBuyingSignal(),
        ShortInterestMomentumSignal(),
    ]
    if sector_map:
        sigs.append(
            SectorRelativeStrengthSignal(
                sector_map=sector_map,
                sector_prices=sector_prices or {},
            )
        )
    return sigs


def _inject_live_data(signals: list[Signal], symbols: list[str], as_of: date) -> None:
    """Populate each signal's symbol-keyed data dict from live sources.

    Every helper is a no-op for signals it doesn't recognise and for signals
    whose data dict is already populated (tests pre-seed data to stay offline),
    so each live fetch runs exactly once across the whole signal set.
    """
    for s in signals:
        try:
            _inject_earnings_events(s, symbols=symbols, ref_date=as_of)
            _inject_recommendations(s, symbols=symbols, ref_date=as_of)
            _inject_insider_events(s, symbols=symbols, ref_date=as_of)
            _inject_short_interest(s, symbols=symbols)
        except Exception:
            logger.exception("Data injection failed for signal %s", getattr(s, "name", s))


def compute_snapshots(
    symbols: list[str],
    *,
    as_of: date | None = None,
    days_back: int = DAYS_BACK,
    signals: list[Signal] | None = None,
    sector_map: dict[str, str] | None = None,
) -> dict[str, dict[str, SignalResult]]:
    """Return ``{symbol: {signal_name: SignalResult}}`` for *symbols* at *as_of*.

    Live data is fetched once per source, then each symbol's bars drive the
    per-symbol ``compute()``. Symbols with too little history are skipped.

    When *signals* is None and *sector_map* is provided, sector ETF prices are
    fetched live (via yfinance) and SectorRS is included as the 5th signal.
    """
    as_of = as_of or date.today()
    if signals is None:
        sector_prices = (
            _fetch_sector_etf_prices(list(set(sector_map.values()))) if sector_map else {}
        )
        signals = build_signals(sector_map=sector_map, sector_prices=sector_prices)
    _inject_live_data(signals, symbols, as_of)

    out: dict[str, dict[str, SignalResult]] = {}
    for sym in symbols:
        bars = bars_from_db(sym, days_back=days_back, ref_date=as_of)
        if not bars or len(bars) < WARMUP_BARS:
            logger.info("Skip %s: only %d bars (< %d)", sym, len(bars) if bars else 0, WARMUP_BARS)
            continue
        ctx = SignalContext(symbol=sym, as_of=as_of, bars=_bars_to_dataframe(bars))
        per_signal: dict[str, SignalResult] = {}
        for s in signals:
            try:
                per_signal[s.name] = s.compute(ctx)
            except Exception as exc:
                logger.warning("Signal %s failed for %s: %s", s.name, sym, exc)
                per_signal[s.name] = SignalResult(
                    score=0.0, confidence=0.0, notes=[f"error: {exc}"]
                )
        out[sym] = per_signal
    return out


def _row_fields(symbol: str, as_of: date, per_signal: dict[str, SignalResult]) -> dict:
    payload = {
        name: {"score": r.score, "confidence": r.confidence, "notes": r.notes}
        for name, r in per_signal.items()
    }
    scores = [r.score for r in per_signal.values()]
    confidences = [r.confidence for r in per_signal.values()]
    return {
        "symbol": symbol.upper(),
        "as_of": as_of,
        "composite_score": sum(scores) / len(scores) if scores else 0.0,
        "composite_confidence": sum(confidences) / len(confidences) if confidences else 0.0,
        "active_count": sum(1 for r in per_signal.values() if r.score > 0),
        "signals_json": json.dumps(payload),
    }


def persist_snapshots(
    results: dict[str, dict[str, SignalResult]],
    *,
    as_of: date,
    engine: Engine | None = None,
) -> int:
    """Upsert one SignalSnapshot per symbol keyed by (symbol, as_of). Returns count."""
    from sqlmodel import Session, select

    eng = engine or _engine.get_engine()
    n = 0
    with Session(eng) as session:
        for sym, per_signal in results.items():
            fields = _row_fields(sym, as_of, per_signal)
            existing = session.exec(
                select(SignalSnapshot).where(
                    SignalSnapshot.symbol == fields["symbol"],
                    SignalSnapshot.as_of == as_of,
                )
            ).first()
            if existing is not None:
                existing.composite_score = fields["composite_score"]
                existing.composite_confidence = fields["composite_confidence"]
                existing.active_count = fields["active_count"]
                existing.signals_json = fields["signals_json"]
                session.add(existing)
            else:
                session.add(SignalSnapshot(**fields))
            n += 1
        session.commit()
    return n


def latest_snapshot(symbol: str, *, engine: Engine | None = None) -> SignalSnapshot | None:
    """Return the most-recent SignalSnapshot for *symbol*, or None."""
    from sqlmodel import Session, select

    eng = engine or _engine.get_engine()
    with Session(eng) as session:
        return session.exec(
            select(SignalSnapshot)
            .where(SignalSnapshot.symbol == symbol.upper())
            .order_by(SignalSnapshot.as_of.desc())  # type: ignore[attr-defined]
        ).first()


def run(
    *,
    symbols: list[str] | None = None,
    as_of: date | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Compute and persist snapshots for *symbols* (default: the DB watchlist)."""
    _engine.init_schema()
    sector_map: dict[str, str] | None = None
    if symbols is None:
        from ai_agent.watchlist import load_watchlist_from_db

        watchlist = load_watchlist_from_db()
        symbols = watchlist.symbols
        sector_map = _build_sector_map(watchlist)
    as_of = as_of or date.today()

    results = compute_snapshots(symbols, as_of=as_of, sector_map=sector_map)
    active = sum(1 for ps in results.values() if any(r.score > 0 for r in ps.values()))
    logger.info(
        "Computed signals for %d/%d symbols; %d have at least one active signal",
        len(results),
        len(symbols),
        active,
    )
    if dry_run:
        return {"symbols": len(results), "active": active, "persisted": 0}
    persisted = persist_snapshots(results, as_of=as_of)
    return {"symbols": len(results), "active": active, "persisted": persisted}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute and log without writing to the DB"
    )
    args = parser.parse_args(argv)
    counts = run(dry_run=args.dry_run)
    logger.info("Done: %s", counts)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
    sys.exit(main())
