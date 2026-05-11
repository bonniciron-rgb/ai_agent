"""Unified backtest validation for all 5 shipped signals (A1, A2, B2, A3, B5).

Backtest v2 — fixes applied after first real-data run (2026-05-11):
  - Extended window: 4 years (2022-2026) to include the 2022 bear market
  - A1 retune: holding 20d (was 5d), threshold 3% (was 2%) — stops overtrading
  - A2 retune: surprise_threshold 3% (was 5%) — widens the firing window
  - B2 retune: min_consecutive_months=2 (was 3) — more signals, lower bar for streak
  - A3 separate universe: mid-cap / regional names where officers make direct buys
  - B5 separate universe: names with historically elevated short float (>= 15%)
    NOTE: shortPercentOfFloat is a live snapshot from yfinance, not historised.
    B5 backtesting reflects current short interest applied to historical prices.
    The signal is designed for live trading; backtest is indicative only.

Pulls real market data directly from yfinance (prices, short interest),
Finnhub (earnings calendar, analyst recommendations), and SEC EDGAR (Form 4
insider transactions) — bypassing the DB-backed runner.

Writes a consolidated JSON report to ``backtest_results.json`` (and stdout).

Requires:
  - FINNHUB_API_KEY env var (for A2 / B2)
  - Internet access to yfinance + SEC EDGAR (for A3 / B5)

Usage::

    FINNHUB_API_KEY=… python scripts/run_all_backtests.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_agent.backtest.engine import run_backtest
from ai_agent.backtest.metrics import equity_from_benchmark
from ai_agent.backtest.metrics import summary as metrics_summary
from ai_agent.data.finnhub_source import FinnhubSource
from ai_agent.data.sec_edgar_source import SecEdgarSource
from ai_agent.signals.analyst_revisions import (
    AnalystRevisionMomentumSignal,
    RecommendationSnapshot,
)
from ai_agent.signals.insider_buying import InsiderBuyingSignal
from ai_agent.signals.pead import EarningsEvent, PostEarningsDriftSignal
from ai_agent.signals.runner import SYMBOL_TO_CIK
from ai_agent.signals.sector_rs import SectorRelativeStrengthSignal
from ai_agent.signals.short_interest import ShortInterestMomentumSignal
from ai_agent.signals.strategy_adapter import SignalStrategy

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("run_all_backtests")

# ── Universe & period ─────────────────────────────────────────────────────────

# A1 / A2 / B2: large-cap sector universe (unchanged from v1)
SECTOR_MAP: dict[str, str] = {
    "AAPL": "XLK",
    "MSFT": "XLK",
    "GOOGL": "XLK",
    "JPM": "XLF",
    "BAC": "XLF",
    "GS": "XLF",
    "XOM": "XLE",
    "CVX": "XLE",
    "JNJ": "XLV",
    "PFE": "XLV",
    "UNH": "XLV",
    "KO": "XLP",
    "PEP": "XLP",
    "PG": "XLP",
    "AMZN": "XLY",
    "HD": "XLY",
    "TSLA": "XLY",
}
LARGE_CAP_SYMBOLS = sorted(SECTOR_MAP.keys())
ETFS = sorted(set(SECTOR_MAP.values()))
BENCHMARK = "SPY"

# A3: mid-cap / regional names where officers make direct open-market buys.
# Large-cap officers overwhelmingly receive options/RSUs, rarely buy shares.
# Cohen-Malloy-Pomorski (2012) edge is strongest in this tier.
A3_SYMBOLS = [
    "RF",  # Regions Financial — regional bank officers buy on rate dips
    "KEY",  # KeyCorp — same pattern
    "FITB",  # Fifth Third Bancorp
    "DVN",  # Devon Energy — E&P management historically buys on commodity dips
    "APA",  # APA Corporation — same
    "GPS",  # Gap Inc — retail, known insider purchase history
    "M",  # Macy's — retail underdog, officer purchases in restructuring years
    "KSS",  # Kohl's — same distressed-retail insider buying pattern
]

# B5: names with historically elevated short float.
# shortPercentOfFloat is a live snapshot — applied to historical prices.
# Signal is indicative for backtesting; designed for live use.
B5_SYMBOLS = [
    "BYND",  # Beyond Meat -- typically 40-50% short float
    "PLUG",  # Plug Power -- hydrogen, typically 15-25% short float
    "LCID",  # Lucid Group -- EV, typically 12-20% short float
    "SOFI",  # SoFi Technologies -- fintech, typically 5-12% short float
    "RIVN",  # Rivian -- EV, typically 8-15% short float
    "TSLA",  # Tesla -- historically 15-25%, bridges large-cap and high-short tier
]

ALL_SYMBOLS_UNION = sorted(set(LARGE_CAP_SYMBOLS) | set(A3_SYMBOLS) | set(B5_SYMBOLS))

END = date.today()
START = END - timedelta(days=1460)  # 4 years — includes 2022 bear market

INITIAL_CAPITAL = 10_000.0
ENTRY_THRESHOLD = 0.3
EXIT_THRESHOLD = 0.0


# ── Data fetchers ─────────────────────────────────────────────────────────────
def fetch_prices(tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    """Download OHLCV from yfinance for all tickers at once."""
    logger.info("yfinance: downloading %d tickers (%s → %s)", len(tickers), start, end)
    raw = yf.download(
        tickers,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    result: dict[str, pd.DataFrame] = {}
    for sym in tickers:
        try:
            sub = raw.xs(sym.upper(), axis=1, level=1) if raw.columns.nlevels > 1 else raw.copy()
            sub = sub.rename(columns=str.lower)
            cols = [c for c in ["open", "high", "low", "close", "volume"] if c in sub.columns]
            sub = sub[cols].dropna()
            if not sub.empty:
                result[sym.upper()] = sub
        except Exception as exc:
            logger.warning("yfinance extract failed for %s: %s", sym, exc)
    logger.info("yfinance: got %d / %d tickers", len(result), len(tickers))
    return result


def fetch_short_interest(symbols: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info
            out[sym] = float(info.get("shortPercentOfFloat") or 0.0)
        except Exception as exc:
            logger.warning("short interest fetch failed for %s: %s — defaulting 0.0", sym, exc)
            out[sym] = 0.0
    return out


def fetch_earnings(
    finnhub: FinnhubSource, symbols: list[str], ref_date: date, lookback_days: int
) -> dict[str, list[EarningsEvent]]:
    start = ref_date - timedelta(days=lookback_days)
    out: dict[str, list[EarningsEvent]] = {}
    for sym in symbols:
        try:
            raw = finnhub.earnings_calendar(sym, start=start, end=ref_date)
        except Exception as exc:
            logger.warning("Finnhub earnings failed for %s: %s", sym, exc)
            continue
        events: list[EarningsEvent] = []
        for ev in raw:
            if ev.eps_actual is None or ev.eps_estimate is None or ev.eps_estimate == 0:
                continue
            surprise = (ev.eps_actual - ev.eps_estimate) / abs(ev.eps_estimate)
            events.append(
                EarningsEvent(
                    announcement_date=ev.event_date,
                    actual_eps=ev.eps_actual,
                    consensus_eps=ev.eps_estimate,
                    surprise_pct=surprise,
                )
            )
        out[sym] = events
        time.sleep(0.05)
    return out


def fetch_recommendations(
    finnhub: FinnhubSource, symbols: list[str]
) -> dict[str, list[RecommendationSnapshot]]:
    out: dict[str, list[RecommendationSnapshot]] = {}
    for sym in symbols:
        try:
            raw = finnhub.recommendation_trends(sym)
        except Exception as exc:
            logger.warning("Finnhub recs failed for %s: %s", sym, exc)
            continue
        snaps: list[RecommendationSnapshot] = []
        for row in raw:
            try:
                snaps.append(
                    RecommendationSnapshot(
                        period=date.fromisoformat(row["period"]),
                        strong_buy=int(row.get("strongBuy") or 0),
                        buy=int(row.get("buy") or 0),
                        hold=int(row.get("hold") or 0),
                        sell=int(row.get("sell") or 0),
                        strong_sell=int(row.get("strongSell") or 0),
                    )
                )
            except (KeyError, ValueError):
                continue
        snaps.sort(key=lambda s: s.period)
        out[sym] = snaps
        time.sleep(0.05)
    return out


def fetch_insider_events(symbols: list[str], lookback_days: int = 90) -> dict[str, list]:
    sec_ua = os.environ.get(
        "SEC_EDGAR_USER_AGENT",
        "Ethera Trading research@etheratrading.example",
    )
    sec = SecEdgarSource(user_agent=sec_ua)
    out: dict[str, list] = {}
    for sym in symbols:
        cik = SYMBOL_TO_CIK.get(sym.upper()) or SecEdgarSource.symbol_to_cik(sym)
        if not cik:
            logger.warning("No CIK mapping for %s — skipping insider data", sym)
            continue
        try:
            filings = sec.recent_form4_filings(cik, days_back=lookback_days)
        except Exception as exc:
            logger.warning("SEC filings list failed for %s: %s", sym, exc)
            continue
        events = []
        for f in filings:
            try:
                events.extend(sec.parse_form4_filing(f["accession_number"], cik))
            except Exception as exc:
                logger.warning("SEC parse %s %s: %s", sym, f["accession_number"], exc)
                continue
            time.sleep(0.15)
        events.sort(key=lambda e: e.transaction_date)
        out[sym] = events
        logger.info("SEC: %d Form 4 events for %s (CIK %s)", len(events), sym, cik)
    return out


# ── Per-signal backtest runner ────────────────────────────────────────────────
def run_signal_backtest(
    signal,
    symbols: list[str],
    price_data: dict[str, pd.DataFrame],
    bench_close: pd.Series,
    *,
    label: str,
    holding_days: int = 5,
) -> dict:
    """Run *signal* against *symbols*; return portfolio metrics dict."""
    per_symbol: dict[str, dict] = {}
    portfolio_equity = pd.Series(dtype="float64")
    total_trades = 0

    for sym in symbols:
        if sym not in price_data or price_data[sym].empty:
            continue
        df = price_data[sym].copy()
        df.index = pd.to_datetime(df.index)
        df = df[(df.index.date >= START) & (df.index.date <= END)]
        if len(df) < 100:
            continue

        strategy = SignalStrategy(
            signal=signal,
            symbol=sym,
            entry_threshold=ENTRY_THRESHOLD,
            exit_threshold=EXIT_THRESHOLD,
            holding_days=holding_days,
        )
        result = run_backtest(df, strategy, symbol=sym, initial_capital=INITIAL_CAPITAL)
        sym_sum = metrics_summary(result.equity_curve, result.trades)
        per_symbol[sym] = {
            "sharpe": round(sym_sum.get("sharpe") or 0.0, 4),
            "cagr": round(sym_sum.get("cagr") or 0.0, 4),
            "max_drawdown": round(sym_sum.get("max_drawdown") or 0.0, 4),
            "win_rate": round(sym_sum.get("win_rate") or 0.0, 4),
            "trades": len(result.trades),
        }
        total_trades += len(result.trades)

        normalized = result.equity_curve / INITIAL_CAPITAL
        if portfolio_equity.empty:
            portfolio_equity = normalized
        else:
            portfolio_equity = portfolio_equity.add(normalized, fill_value=1.0)

    if portfolio_equity.empty:
        logger.warning("[%s] no symbols produced data — skipping", label)
        return {"signal": label, "metrics": None, "per_symbol": {}}

    portfolio_equity = (portfolio_equity / len(per_symbol)) * INITIAL_CAPITAL
    p = metrics_summary(portfolio_equity, [], benchmark=bench_close)
    return {
        "signal": label,
        "signal_name": signal.name,
        "signal_version": signal.version,
        "period": [START.isoformat(), END.isoformat()],
        "symbols": list(per_symbol.keys()),
        "metrics": {
            "sharpe": round(p.get("sharpe") or 0.0, 4),
            "cagr": round(p.get("cagr") or 0.0, 4),
            "max_drawdown": round(p.get("max_drawdown") or 0.0, 4),
            "win_rate": round(p.get("win_rate") or 0.0, 4),
            "alpha": round(p.get("alpha") or 0.0, 4),
            "trade_count": total_trades,
        },
        "per_symbol": per_symbol,
    }


# ── Main orchestration ────────────────────────────────────────────────────────
def main() -> int:
    logger.info("=" * 70)
    logger.info("Ethera Trading — unified signal backtest v2")
    logger.info(
        "Large-cap: %d  A3 mid-cap: %d  B5 high-short: %d  period %s → %s",
        len(LARGE_CAP_SYMBOLS),
        len(A3_SYMBOLS),
        len(B5_SYMBOLS),
        START,
        END,
    )
    logger.info("=" * 70)

    # 1. Prices — one download covers all universes
    all_tickers = sorted(set(ALL_SYMBOLS_UNION) | set(ETFS) | {BENCHMARK})
    price_data = fetch_prices(all_tickers, START, END)

    # 2. Benchmark
    bench_df = price_data.get(BENCHMARK)
    if bench_df is None or bench_df.empty:
        logger.error("No SPY benchmark data — aborting")
        return 1
    bench_close = bench_df["close"].copy()
    bench_close.index = pd.to_datetime(bench_close.index)
    bench_close = bench_close[(bench_close.index.date >= START) & (bench_close.index.date <= END)]
    bench_equity = equity_from_benchmark(bench_close, initial_capital=INITIAL_CAPITAL)
    bench_metrics = metrics_summary(bench_equity, [])

    # 3. Sector ETF closes for A1
    sector_prices: dict[str, pd.Series] = {}
    for etf in [*ETFS, BENCHMARK]:
        if etf in price_data and not price_data[etf].empty:
            s = price_data[etf]["close"].copy()
            s.index = pd.to_datetime(s.index).date
            sector_prices[etf] = s

    # 4. Finnhub (A2 + B2)
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    earnings_by_sym: dict[str, list[EarningsEvent]] = {}
    recs_by_sym: dict[str, list[RecommendationSnapshot]] = {}
    if finnhub_key:
        fh = FinnhubSource(finnhub_key)
        logger.info("Finnhub: fetching earnings + recommendation trends ...")
        earnings_by_sym = fetch_earnings(fh, LARGE_CAP_SYMBOLS, ref_date=END, lookback_days=1460)
        recs_by_sym = fetch_recommendations(fh, LARGE_CAP_SYMBOLS)
    else:
        logger.warning("FINNHUB_API_KEY not set — A2 / B2 backtests will have no data")

    # 5. SEC EDGAR Form 4 (A3 — mid-cap universe only)
    logger.info("SEC EDGAR: fetching Form 4 filings for A3 mid-cap universe ...")
    insider_by_sym = fetch_insider_events(A3_SYMBOLS, lookback_days=1460)

    # 6. Short interest snapshots (B5 high-short universe)
    logger.info("yfinance: fetching short interest snapshots for B5 universe ...")
    short_data = fetch_short_interest(B5_SYMBOLS)
    logger.info(
        "Short interest: %s",
        {s: f"{v:.1%}" for s, v in short_data.items()},
    )

    # 7. Run signals
    reports: list[dict] = []

    logger.info("-" * 70)
    logger.info("A1: Sector Relative Strength (retune: 20d hold, 3%% threshold)")
    a1 = SectorRelativeStrengthSignal(
        sector_map=SECTOR_MAP,
        sector_prices=sector_prices,
        lookback=20,
        threshold=0.03,  # raised from 0.02 — reduces false positives
    )
    reports.append(
        run_signal_backtest(
            a1, LARGE_CAP_SYMBOLS, price_data, bench_close, label="A1_sector_rs", holding_days=20
        )
    )

    logger.info("-" * 70)
    logger.info("A2: Post-Earnings Drift (retune: 3%% surprise threshold)")
    a2 = PostEarningsDriftSignal(
        earnings_events=earnings_by_sym,
        surprise_threshold=0.03,  # lowered from 0.05 — widens trigger
    )
    reports.append(
        run_signal_backtest(
            a2, LARGE_CAP_SYMBOLS, price_data, bench_close, label="A2_pead", holding_days=20
        )
    )

    logger.info("-" * 70)
    logger.info("B2: Analyst Revision Momentum (retune: 2 consecutive months)")
    b2 = AnalystRevisionMomentumSignal(
        recommendations=recs_by_sym,
        min_consecutive_months=2,  # lowered from 3 — more signals, still requires trend
    )
    reports.append(
        run_signal_backtest(
            b2,
            LARGE_CAP_SYMBOLS,
            price_data,
            bench_close,
            label="B2_analyst_rev",
            holding_days=20,
        )
    )

    logger.info("-" * 70)
    logger.info("A3: Insider Buying — mid-cap universe (RF, KEY, FITB, DVN, APA, GPS, M, KSS)")
    a3 = InsiderBuyingSignal(insider_events=insider_by_sym)
    reports.append(
        run_signal_backtest(
            a3, A3_SYMBOLS, price_data, bench_close, label="A3_insider", holding_days=20
        )
    )

    logger.info("-" * 70)
    logger.info("B5: Short Squeeze — high-short universe (BYND, PLUG, LCID, SOFI, RIVN, TSLA)")
    b5 = ShortInterestMomentumSignal(short_data=short_data, min_short_pct=0.15)
    reports.append(
        run_signal_backtest(
            b5, B5_SYMBOLS, price_data, bench_close, label="B5_short_squeeze", holding_days=10
        )
    )

    # 8. Output
    output = {
        "as_of": END.isoformat(),
        "version": "v2",
        "period": [START.isoformat(), END.isoformat()],
        "universes": {
            "large_cap": LARGE_CAP_SYMBOLS,
            "a3_midcap": A3_SYMBOLS,
            "b5_high_short": B5_SYMBOLS,
        },
        "benchmark": {
            "symbol": BENCHMARK,
            "sharpe": round(bench_metrics.get("sharpe") or 0.0, 4),
            "cagr": round(bench_metrics.get("cagr") or 0.0, 4),
            "max_drawdown": round(bench_metrics.get("max_drawdown") or 0.0, 4),
        },
        "data_coverage": {
            "price_symbols": len(price_data),
            "earnings_symbols": sum(1 for v in earnings_by_sym.values() if v),
            "recommendation_symbols": sum(1 for v in recs_by_sym.values() if v),
            "insider_symbols": sum(1 for v in insider_by_sym.values() if v),
            "short_interest_symbols": sum(1 for v in short_data.values() if v > 0),
            "b5_note": (
                "shortPercentOfFloat is a live snapshot. "
                "B5 backtest applies current short interest to historical prices — indicative only."
            ),
        },
        "signals": reports,
    }

    out_path = Path(os.environ.get("BACKTEST_OUTPUT", "backtest_results.json"))
    out_path.write_text(json.dumps(output, indent=2, default=str))
    print(json.dumps(output, indent=2, default=str))
    logger.info("Wrote %s", out_path)

    print("\n" + "=" * 70)
    print(f"{'Signal':<22} {'Sharpe':>8} {'CAGR':>8} {'MaxDD':>8} {'Alpha':>8} {'Trades':>8}")
    print("-" * 70)
    bm = output["benchmark"]
    print(
        f"{'SPY (4yr benchmark)':<22} {bm['sharpe']:>8.2f} {bm['cagr'] * 100:>7.1f}% "
        f"{bm['max_drawdown'] * 100:>7.1f}% {'—':>8} {'—':>8}"
    )
    for r in reports:
        m = r["metrics"]
        if m is None:
            print(f"{r['signal']:<22} {'—':>8} {'—':>8} {'—':>8} {'—':>8} {'—':>8}")
            continue
        print(
            f"{r['signal']:<22} {m['sharpe']:>8.2f} {m['cagr'] * 100:>7.1f}% "
            f"{m['max_drawdown'] * 100:>7.1f}% {m['alpha'] * 100:>7.1f}% {m['trade_count']:>8}"
        )
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
