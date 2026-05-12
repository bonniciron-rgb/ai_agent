"""Unified backtest validation — v3 strategic pivot.

Backtest v3 — strategic pivot after v1/v2 showed 0/5 signals beat SPY:
  - DROPPED A3 (insider) — dynamic CIK lookup broken, mid-cap data sparse
  - DROPPED B5 (short squeeze) — catastrophic falling-knife trap (-0.9 Sharpe)
  - REVERTED B2 to min_consecutive_months=3 (v1 had Sharpe 1.51; relaxing degraded it)
  - KEPT A1 retune from v2: holding 20d, threshold 3%
  - KEPT A2 retune from v2: surprise_threshold=3%
  - NEW: CompositeFactorSignal blending A1+A2+B2 with continuous scoring
    -> the real test of whether multi-factor blend has edge vs SPY

Strategic reframe: not "alpha generator picking individual stocks" but
"disciplined exposure manager modulating SPY allocation 50-150% based on
factor signals". See etheratrading.md top-of-doc.

Pulls real market data from yfinance (prices) + Finnhub (earnings + recs).
SEC EDGAR + short interest fetches removed (A3/B5 deprecated).

Writes ``backtest_results.json``.

Requires:
  - FINNHUB_API_KEY env var (for A2 / B2 / composite)
  - Internet access to yfinance

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
from ai_agent.backtest.spy_tilt import SpyTiltStrategy
from ai_agent.data.finnhub_source import FinnhubSource
from ai_agent.signals.analyst_revisions import (
    AnalystRevisionMomentumSignal,
    RecommendationSnapshot,
)
from ai_agent.signals.composite import CompositeFactorSignal
from ai_agent.signals.pead import EarningsEvent, PostEarningsDriftSignal
from ai_agent.signals.sector_rs import SectorRelativeStrengthSignal
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


def run_spy_tilt_backtest(
    signal,
    universe_price_data: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    bench_close: pd.Series,
    *,
    label: str,
    min_alloc: float = 0.5,
    max_alloc: float = 1.0,
) -> dict:
    """Run SPY-tilt exposure-manager backtest using *signal* over *universe_price_data*.

    Maps the average composite score across the universe to a SPY allocation
    fraction in [min_alloc, max_alloc] and rebalances SPY accordingly.
    """
    filtered: dict[str, pd.DataFrame] = {}
    for sym, df in universe_price_data.items():
        d = df.copy()
        d.index = pd.to_datetime(d.index)
        d = d[(d.index.date >= START) & (d.index.date <= END)]
        if len(d) >= 100:
            filtered[sym] = d

    if not filtered:
        logger.warning("[%s] no universe symbols with sufficient data — skipping", label)
        return {"signal": label, "metrics": None}

    spy_filtered = spy_df.copy()
    spy_filtered.index = pd.to_datetime(spy_filtered.index)
    spy_filtered = spy_filtered[
        (spy_filtered.index.date >= START) & (spy_filtered.index.date <= END)
    ]

    strategy = SpyTiltStrategy(
        signal=signal,
        universe_bars=filtered,
        min_alloc=min_alloc,
        max_alloc=max_alloc,
        rebalance_threshold=0.05,
        warmup_bars=50,
    )
    logger.info("[%s] pre-computing universe scores ...", label)
    result = run_backtest(spy_filtered, strategy, symbol="SPY", initial_capital=INITIAL_CAPITAL)
    p = metrics_summary(result.equity_curve, result.trades, benchmark=bench_close)
    return {
        "signal": label,
        "signal_name": signal.name,
        "signal_version": signal.version,
        "period": [START.isoformat(), END.isoformat()],
        "universe_symbols": list(filtered.keys()),
        "spy_tilt": {"min_alloc": min_alloc, "max_alloc": max_alloc},
        "metrics": {
            "sharpe": round(p.get("sharpe") or 0.0, 4),
            "cagr": round(p.get("cagr") or 0.0, 4),
            "max_drawdown": round(p.get("max_drawdown") or 0.0, 4),
            "win_rate": round(p.get("win_rate") or 0.0, 4),
            "alpha": round(p.get("alpha") or 0.0, 4),
            "trade_count": len(result.trades),
        },
    }


# ── Main orchestration ────────────────────────────────────────────────────────
def main() -> int:
    logger.info("=" * 70)
    logger.info("Ethera Trading — unified signal backtest v2")
    logger.info(
        "Universe: %d large-cap symbols, period %s → %s",
        len(LARGE_CAP_SYMBOLS),
        START,
        END,
    )
    logger.info("=" * 70)

    # 1. Prices for all stocks + sector ETFs + benchmark
    all_tickers = sorted(set(LARGE_CAP_SYMBOLS) | set(ETFS) | {BENCHMARK})
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

    # 5. Run individual signals + composite
    reports: list[dict] = []

    logger.info("-" * 70)
    logger.info("A1: Sector Relative Strength (20d hold, 3%% threshold)")
    a1 = SectorRelativeStrengthSignal(
        sector_map=SECTOR_MAP,
        sector_prices=sector_prices,
        lookback=20,
        threshold=0.03,
    )
    reports.append(
        run_signal_backtest(
            a1, LARGE_CAP_SYMBOLS, price_data, bench_close, label="A1_sector_rs", holding_days=20
        )
    )

    logger.info("-" * 70)
    logger.info("A2: Post-Earnings Drift (3%% surprise threshold)")
    a2 = PostEarningsDriftSignal(
        earnings_events=earnings_by_sym,
        surprise_threshold=0.03,
    )
    reports.append(
        run_signal_backtest(
            a2, LARGE_CAP_SYMBOLS, price_data, bench_close, label="A2_pead", holding_days=20
        )
    )

    logger.info("-" * 70)
    logger.info("B2: Analyst Revision Momentum (3 consecutive months -- reverted from v2)")
    b2 = AnalystRevisionMomentumSignal(
        recommendations=recs_by_sym,
        # min_consecutive_months defaults to 3 -- v1 config with Sharpe 1.51
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
    logger.info("CompositeFactorSignal: equal-weight blend of A1 + A2 + B2")
    composite = CompositeFactorSignal(
        sub_signals=[a1, a2, b2],
        name_suffix="equal_weight",
    )
    reports.append(
        run_signal_backtest(
            composite,
            LARGE_CAP_SYMBOLS,
            price_data,
            bench_close,
            label="Composite_equal",
            holding_days=20,
        )
    )

    logger.info("-" * 70)
    logger.info("SPY Tilt (50-100%%): composite score modulates SPY allocation")
    universe_bars = {
        sym: price_data[sym]
        for sym in LARGE_CAP_SYMBOLS
        if sym in price_data and not price_data[sym].empty
    }
    bench_df = price_data.get(BENCHMARK)
    if bench_df is not None and not bench_df.empty:
        reports.append(
            run_spy_tilt_backtest(
                composite,
                universe_bars,
                bench_df,
                bench_close,
                label="SPY_tilt_50_100",
                min_alloc=0.5,
                max_alloc=1.0,
            )
        )

    # 6. Output
    output = {
        "as_of": END.isoformat(),
        "version": "v3",
        "strategy": "exposure_manager",
        "period": [START.isoformat(), END.isoformat()],
        "universe": LARGE_CAP_SYMBOLS,
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
