"""Macro market regime classifier.

Reads SPY + ^VIX bars from the DB, computes SMAs, and classifies the
current regime as one of: bull, bear, crisis, correction, sideways, mixed.

Run::

    python -m ai_agent.macro.regime_detector
    # or
    python scripts/macro_regime.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd
from sqlmodel import Session, select

from ai_agent.data.yfinance_source import YFinanceSource
from ai_agent.db.engine import get_engine, init_schema
from ai_agent.db.models import Bar, MacroRegimeSnapshot
from ai_agent.features.indicators import sma
from ai_agent.loop.bar_store import ingest_bars

logger = logging.getLogger(__name__)

REGIMES = ("bull", "bear", "crisis", "correction", "sideways", "mixed")


@dataclass
class MacroRegime:
    as_of: date
    regime: str
    spy_close: Decimal
    spy_sma_50: Decimal
    spy_sma_200: Decimal
    spy_above_200sma: bool
    spy_50_over_200sma: bool
    vix_close: Decimal
    vix_sma_20: Decimal | None
    notes: list[str]


def classify_macro_regime(
    *,
    as_of: date,
    spy_close: Decimal,
    spy_sma_50: Decimal,
    spy_sma_200: Decimal,
    vix_close: Decimal,
    vix_sma_20: Decimal | None = None,
) -> MacroRegime:
    notes: list[str] = []

    if vix_close >= Decimal("30"):
        notes.append(f"VIX {vix_close:.1f} >= 30 (crisis)")
        regime = "crisis"

    elif spy_close < spy_sma_200 and spy_close < spy_sma_50 and vix_close > Decimal("22"):
        notes.append("SPY below both 50d and 200d SMA")
        notes.append(f"VIX {vix_close:.1f} > 22 (elevated)")
        regime = "bear"

    elif spy_close < spy_sma_200 and spy_close < spy_sma_50:
        notes.append("SPY below both 50d and 200d SMA")
        notes.append(f"VIX {vix_close:.1f} (not yet elevated)")
        regime = "correction"

    elif spy_close > spy_sma_50 > spy_sma_200 and vix_close < Decimal("20"):
        notes.append("SPY above 50d > 200d (golden cross structure)")
        notes.append(f"VIX {vix_close:.1f} < 20 (calm)")
        regime = "bull"

    elif abs(spy_close - spy_sma_200) / spy_sma_200 < Decimal("0.05"):
        pct = abs(spy_close - spy_sma_200) / spy_sma_200 * Decimal("100")
        notes.append(f"SPY within +-5% of 200d SMA ({pct:.1f}%)")
        regime = "sideways"

    else:
        notes.append("No clean trend or vol signal -- mixed regime")
        regime = "mixed"

    spy_above_200sma = spy_close > spy_sma_200
    spy_50_over_200sma = spy_sma_50 > spy_sma_200

    return MacroRegime(
        as_of=as_of,
        regime=regime,
        spy_close=spy_close,
        spy_sma_50=spy_sma_50,
        spy_sma_200=spy_sma_200,
        spy_above_200sma=spy_above_200sma,
        spy_50_over_200sma=spy_50_over_200sma,
        vix_close=vix_close,
        vix_sma_20=vix_sma_20,
        notes=notes,
    )


def compute_and_save(
    *,
    as_of: date | None = None,
    engine=None,
) -> MacroRegimeSnapshot | None:
    as_of = as_of or datetime.now(UTC).date()
    eng = engine or get_engine()

    try:
        ingest_bars(["SPY", "^VIX"], source=YFinanceSource(), days_back=300)
    except Exception:
        logger.exception("Bar ingest failed — proceeding with existing DB data")

    with Session(eng) as session:
        spy_rows = list(
            session.exec(
                select(Bar)
                .where(Bar.symbol == "SPY")
                .order_by(Bar.trading_date.desc())  # type: ignore[arg-type]
                .limit(220)
            ).all()
        )
        vix_rows = list(
            session.exec(
                select(Bar)
                .where(Bar.symbol == "^VIX")
                .order_by(Bar.trading_date.desc())  # type: ignore[arg-type]
                .limit(220)
            ).all()
        )

    if len(spy_rows) < 200:
        logger.warning("Insufficient SPY bars (%d < 200) — skipping regime snapshot", len(spy_rows))
        return None
    if len(vix_rows) < 20:
        logger.warning("Insufficient VIX bars (%d < 20) — skipping regime snapshot", len(vix_rows))
        return None

    spy_rows_asc = sorted(spy_rows, key=lambda r: r.trading_date)
    vix_rows_asc = sorted(vix_rows, key=lambda r: r.trading_date)

    spy_closes = pd.Series(
        [float(r.close) for r in spy_rows_asc],
        index=[r.trading_date for r in spy_rows_asc],
    )
    vix_closes = pd.Series(
        [float(r.close) for r in vix_rows_asc],
        index=[r.trading_date for r in vix_rows_asc],
    )

    spy_sma_50_val = sma(spy_closes, 50).iloc[-1]
    spy_sma_200_val = sma(spy_closes, 200).iloc[-1]
    vix_sma_20_raw = sma(vix_closes, 20).iloc[-1]
    vix_sma_20_val = None if pd.isna(vix_sma_20_raw) else Decimal(str(vix_sma_20_raw))

    spy_close = Decimal(str(spy_closes.iloc[-1]))
    spy_sma_50 = Decimal(str(spy_sma_50_val))
    spy_sma_200 = Decimal(str(spy_sma_200_val))
    vix_close = Decimal(str(vix_closes.iloc[-1]))

    result = classify_macro_regime(
        as_of=as_of,
        spy_close=spy_close,
        spy_sma_50=spy_sma_50,
        spy_sma_200=spy_sma_200,
        vix_close=vix_close,
        vix_sma_20=vix_sma_20_val,
    )

    with Session(eng) as session:
        existing = session.exec(
            select(MacroRegimeSnapshot).where(MacroRegimeSnapshot.as_of == as_of)
        ).first()

        if existing is not None:
            existing.regime = result.regime
            existing.spy_close = result.spy_close
            existing.spy_sma_50 = result.spy_sma_50
            existing.spy_sma_200 = result.spy_sma_200
            existing.spy_above_200sma = result.spy_above_200sma
            existing.spy_50_over_200sma = result.spy_50_over_200sma
            existing.vix_close = result.vix_close
            existing.vix_sma_20 = result.vix_sma_20
            existing.notes_json = json.dumps(result.notes)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
        else:
            snap = MacroRegimeSnapshot(
                as_of=result.as_of,
                regime=result.regime,
                spy_close=result.spy_close,
                spy_sma_50=result.spy_sma_50,
                spy_sma_200=result.spy_sma_200,
                spy_above_200sma=result.spy_above_200sma,
                spy_50_over_200sma=result.spy_50_over_200sma,
                vix_close=result.vix_close,
                vix_sma_20=result.vix_sma_20,
                notes_json=json.dumps(result.notes),
            )
            session.add(snap)
            session.commit()
            session.refresh(snap)
            return snap


def get_latest_snapshot(engine=None) -> MacroRegimeSnapshot | None:
    eng = engine or get_engine()
    with Session(eng) as session:
        return session.exec(
            select(MacroRegimeSnapshot).order_by(MacroRegimeSnapshot.as_of.desc())  # type: ignore[arg-type]
        ).first()


def get_recent_snapshots(days: int = 30, engine=None) -> list[MacroRegimeSnapshot]:
    eng = engine or get_engine()
    with Session(eng) as session:
        return list(
            session.exec(
                select(MacroRegimeSnapshot)
                .order_by(MacroRegimeSnapshot.as_of.desc())  # type: ignore[arg-type]
                .limit(days)
            ).all()
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify the daily macro market regime.")
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Override the as-of date")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    as_of: date | None = None
    if args.date:
        as_of = date.fromisoformat(args.date)

    init_schema()
    snap = compute_and_save(as_of=as_of)

    if snap is None:
        logger.warning("Regime snapshot not created — insufficient bar data")
    else:
        notes = json.loads(snap.notes_json)
        logger.info(
            "Regime snapshot saved: as_of=%s regime=%s spy_close=%s vix_close=%s notes=%s",
            snap.as_of,
            snap.regime,
            snap.spy_close,
            snap.vix_close,
            notes,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
