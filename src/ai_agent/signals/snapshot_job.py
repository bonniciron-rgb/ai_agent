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
from ai_agent.signals.short_interest import ShortInterestMomentumSignal

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# short_interest needs lookback_days+1 bars; 60 is comfortably above all four.
WARMUP_BARS = 60
DAYS_BACK = 400


def build_signals() -> list[Signal]:
    """The four live event/positioning signals, freshly constructed (empty data)."""
    return [
        PostEarningsDriftSignal(),
        AnalystRevisionMomentumSignal(),
        InsiderBuyingSignal(),
        ShortInterestMomentumSignal(),
    ]


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
) -> dict[str, dict[str, SignalResult]]:
    """Return ``{symbol: {signal_name: SignalResult}}`` for *symbols* at *as_of*.

    Live data is fetched once per source, then each symbol's bars drive the
    per-symbol ``compute()``. Symbols with too little history are skipped.
    """
    as_of = as_of or date.today()
    signals = signals if signals is not None else build_signals()
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
    if symbols is None:
        from ai_agent.watchlist import load_watchlist_from_db

        symbols = load_watchlist_from_db().symbols
    as_of = as_of or date.today()

    results = compute_snapshots(symbols, as_of=as_of)
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
