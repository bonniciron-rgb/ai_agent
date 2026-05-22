"""Rule-based proxy backtest for the live watchlist.

The daily-loop LLM agent decides trades from regime + moving-average + RSI
technicals. Faithfully backtesting the agent itself is expensive and degraded
(news / external signals can't be replayed without look-ahead), so this script
runs the same *kind* of logic with deterministic rule strategies as a cheap
gate:

  - buy_and_hold      : hold each watchlist name for the whole window
  - sma_cross_50_200  : 50/200 SMA golden-cross trend strategy
  - ema_breakout_20   : price-vs-EMA20 momentum strategy

Each strategy runs per watchlist symbol, then the per-symbol equity curves are
aggregated equal-weight into a portfolio curve and compared against SPY
buy-and-hold. If actively trading the watchlist shows no edge over simply
holding it (or holding SPY), an expensive LLM backtest is unlikely to change
that conclusion — invest in the LLM harness only if this gate shows promise.

Writes ``watchlist_backtest_results.json``.

Requires: internet access (yfinance). No API keys needed.

Usage::

    python scripts/run_watchlist_backtest.py

    # custom window (default: trailing 4 years)
    BACKTEST_START=2018-01-01 BACKTEST_END=2022-12-31 \
        python scripts/run_watchlist_backtest.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_agent.backtest.engine import run_backtest
from ai_agent.backtest.metrics import equity_from_benchmark
from ai_agent.backtest.metrics import summary as metrics_summary
from ai_agent.backtest.strategy import EmaBreakoutStrategy, SmaCrossStrategy
from ai_agent.watchlist import load_watchlist

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("run_watchlist_backtest")

BENCHMARK = "SPY"
INITIAL_CAPITAL = 10_000.0
WATCHLIST_PATH = Path(os.environ.get("WATCHLIST_PATH", "config/watchlist.yaml"))
# Calendar days fetched *before* the window so SMA-200 is already armed at START
# (a trend strategy that spends the first 200 bars warming up would otherwise
# look artificially flat against buy-and-hold).
WARMUP_DAYS = 400
MIN_WINDOW_BARS = 100

# A per-symbol backtest runner: (full_history, window_slice, symbol) -> (equity, trades)
Runner = Callable[[pd.DataFrame, pd.DataFrame, str], "tuple[pd.Series, list]"]


def _resolve_period() -> tuple[date, date]:
    """Backtest window; default trailing 4 years. Overridable via env vars."""
    end_env = os.environ.get("BACKTEST_END")
    end = date.fromisoformat(end_env) if end_env else date.today()
    start_env = os.environ.get("BACKTEST_START")
    if start_env:
        start = date.fromisoformat(start_env)
    else:
        lookback = int(os.environ.get("BACKTEST_LOOKBACK_DAYS", "1460"))
        start = end - timedelta(days=lookback)
    if start >= end:
        raise ValueError(f"BACKTEST_START {start} must be before BACKTEST_END {end}")
    return start, end


def fetch_prices(tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    """Download daily OHLCV from yfinance for all tickers at once."""
    logger.info("yfinance: downloading %d tickers (%s → %s)", len(tickers), start, end)
    raw = yf.download(
        tickers,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned no data — check internet access")
    out: dict[str, pd.DataFrame] = {}
    for sym in tickers:
        try:
            sub = raw.xs(sym.upper(), axis=1, level=1) if raw.columns.nlevels > 1 else raw.copy()
            sub = sub.rename(columns=str.lower)
            cols = [c for c in ("open", "high", "low", "close", "volume") if c in sub.columns]
            sub = sub[cols].dropna()
            sub.index = pd.to_datetime(sub.index)
            if not sub.empty:
                out[sym.upper()] = sub.sort_index()
        except Exception as exc:
            logger.warning("yfinance extract failed for %s: %s", sym, exc)
    logger.info("yfinance: got %d / %d tickers", len(out), len(tickers))
    return out


def _window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Slice *df* to the [start, end] backtest window (inclusive)."""
    mask = (df.index.date >= start) & (df.index.date <= end)
    return df[mask]


def _aggregate(curves: list[pd.Series]) -> pd.Series:
    """Equal-weight average of per-symbol equity curves → portfolio NAV."""
    portfolio = pd.Series(dtype="float64")
    for curve in curves:
        normalized = curve / INITIAL_CAPITAL
        portfolio = normalized if portfolio.empty else portfolio.add(normalized, fill_value=1.0)
    return (portfolio / len(curves)) * INITIAL_CAPITAL


# ── Per-symbol strategy runners ─────────────────────────────────────────────


def _buy_and_hold(_full: pd.DataFrame, window: pd.DataFrame, _sym: str) -> tuple[pd.Series, list]:
    return equity_from_benchmark(window["close"], initial_capital=INITIAL_CAPITAL), []


def _sma_cross(full: pd.DataFrame, window: pd.DataFrame, sym: str) -> tuple[pd.Series, list]:
    # Strategy is built on the *full* close (incl. warmup) so its 200-day SMA
    # is already valid on the first bar of the window.
    strategy = SmaCrossStrategy(close=full["close"], fast=50, slow=200)
    result = run_backtest(window, strategy, symbol=sym, initial_capital=INITIAL_CAPITAL)
    return result.equity_curve, result.trades


def _ema_breakout(full: pd.DataFrame, window: pd.DataFrame, sym: str) -> tuple[pd.Series, list]:
    strategy = EmaBreakoutStrategy(close=full["close"], period=20)
    result = run_backtest(window, strategy, symbol=sym, initial_capital=INITIAL_CAPITAL)
    return result.equity_curve, result.trades


# ── Portfolio aggregation ───────────────────────────────────────────────────


def _per_symbol_metrics(curve: pd.Series, trades: list) -> dict:
    s = metrics_summary(curve, trades)
    return {
        "total_return": round(s.get("total_return") or 0.0, 4),
        "cagr": round(s.get("cagr") or 0.0, 4),
        "sharpe": round(s.get("sharpe") or 0.0, 4),
        "max_drawdown": round(s.get("max_drawdown") or 0.0, 4),
        "win_rate": round(s.get("win_rate") or 0.0, 4),
        "trades": len(trades),
    }


def run_portfolio(
    label: str,
    runner: Runner,
    symbols: list[str],
    price_data: dict[str, pd.DataFrame],
    start: date,
    end: date,
    bench_equity: pd.Series,
) -> dict:
    """Run *runner* across *symbols*; aggregate equal-weight; return metrics."""
    curves: list[pd.Series] = []
    per_symbol: dict[str, dict] = {}
    total_trades = 0
    win_rates: list[float] = []

    for sym in symbols:
        full = price_data.get(sym)
        if full is None:
            logger.warning("[%s] %s: no price data — skipped", label, sym)
            continue
        window = _window(full, start, end)
        if len(window) < MIN_WINDOW_BARS:
            logger.warning("[%s] %s: only %d bars in window — skipped", label, sym, len(window))
            continue
        curve, trades = runner(full, window, sym)
        curves.append(curve)
        per_symbol[sym] = _per_symbol_metrics(curve, trades)
        total_trades += len(trades)
        # A win rate is only meaningful once a position has been closed.
        if any(t.side == "sell" for t in trades):
            win_rates.append(per_symbol[sym]["win_rate"])

    if not curves:
        logger.warning("[%s] no symbols produced data — skipping", label)
        return {"portfolio": None, "per_symbol": {}}

    portfolio = _aggregate(curves)
    p = metrics_summary(portfolio, [], benchmark=bench_equity)
    return {
        "portfolio": {
            "total_return": round(p.get("total_return") or 0.0, 4),
            "cagr": round(p.get("cagr") or 0.0, 4),
            "sharpe": round(p.get("sharpe") or 0.0, 4),
            "max_drawdown": round(p.get("max_drawdown") or 0.0, 4),
            "volatility": round(p.get("volatility") or 0.0, 4),
            "alpha": round(p.get("alpha") or 0.0, 4),
            "capm_alpha": round(p.get("capm_alpha") or 0.0, 4),
            "beta": round(p.get("beta") or 0.0, 4),
            "trade_count": total_trades,
            "avg_win_rate": (round(sum(win_rates) / len(win_rates), 4) if win_rates else None),
        },
        "per_symbol": per_symbol,
    }


# ── Main orchestration ──────────────────────────────────────────────────────


def main() -> int:
    start, end = _resolve_period()
    watchlist = load_watchlist(WATCHLIST_PATH)
    symbols = watchlist.symbols
    if not symbols:
        logger.error("Watchlist %s is empty — nothing to backtest", WATCHLIST_PATH)
        return 1

    logger.info("=" * 70)
    logger.info("Watchlist proxy backtest — %d symbols, %s → %s", len(symbols), start, end)
    logger.info("=" * 70)

    # Fetch with a warmup buffer before the window so trend indicators are armed.
    fetch_start = start - timedelta(days=WARMUP_DAYS)
    price_data = fetch_prices([*symbols, BENCHMARK], fetch_start, end)

    bench_df = price_data.get(BENCHMARK)
    if bench_df is None or bench_df.empty:
        logger.error("No %s benchmark data — aborting", BENCHMARK)
        return 1
    bench_window = _window(bench_df, start, end)
    bench_equity = equity_from_benchmark(bench_window["close"], initial_capital=INITIAL_CAPITAL)
    bench_metrics = metrics_summary(bench_equity, [])

    strategies: dict[str, Runner] = {
        "buy_and_hold": _buy_and_hold,
        "sma_cross_50_200": _sma_cross,
        "ema_breakout_20": _ema_breakout,
    }
    results: dict[str, dict] = {}
    for label, runner in strategies.items():
        logger.info("-" * 70)
        logger.info("Running: %s", label)
        results[label] = run_portfolio(label, runner, symbols, price_data, start, end, bench_equity)

    output = {
        "as_of": end.isoformat(),
        "type": "rule_based_proxy",
        "note": (
            "Deterministic rule strategies as a cheap proxy for the LLM agent's "
            "technical logic. NOT the live agent — see scripts/run_watchlist_backtest.py."
        ),
        "period": [start.isoformat(), end.isoformat()],
        "initial_capital": INITIAL_CAPITAL,
        "watchlist": symbols,
        "benchmark": {
            "symbol": BENCHMARK,
            "total_return": round(bench_metrics.get("total_return") or 0.0, 4),
            "cagr": round(bench_metrics.get("cagr") or 0.0, 4),
            "sharpe": round(bench_metrics.get("sharpe") or 0.0, 4),
            "max_drawdown": round(bench_metrics.get("max_drawdown") or 0.0, 4),
        },
        "strategies": results,
    }

    out_path = Path(os.environ.get("BACKTEST_OUTPUT", "watchlist_backtest_results.json"))
    out_path.write_text(json.dumps(output, indent=2, default=str))
    logger.info("Wrote %s", out_path)

    # ── Console summary table ───────────────────────────────────────────────
    bm = output["benchmark"]
    print("\n" + "=" * 78)
    print(f"Watchlist proxy backtest — {start} → {end} ({len(symbols)} symbols)")
    print("=" * 78)
    header = (
        f"{'Strategy':<20}{'TotRet':>9}{'CAGR':>9}{'Sharpe':>9}"
        f"{'MaxDD':>9}{'Alpha':>9}{'Trades':>8}{'WinRate':>9}"
    )
    print(header)
    print("-" * len(header))
    print(
        f"{'SPY (benchmark)':<20}{bm['total_return'] * 100:>8.1f}%"
        f"{bm['cagr'] * 100:>8.1f}%{bm['sharpe']:>9.2f}"
        f"{bm['max_drawdown'] * 100:>8.1f}%{'—':>9}{'—':>8}{'—':>9}"
    )
    for label, res in results.items():
        p = res["portfolio"]
        if p is None:
            print(f"{label:<20}{'— no data —':>54}")
            continue
        win = f"{p['avg_win_rate'] * 100:.0f}%" if p["avg_win_rate"] is not None else "—"
        print(
            f"{label:<20}{p['total_return'] * 100:>8.1f}%{p['cagr'] * 100:>8.1f}%"
            f"{p['sharpe']:>9.2f}{p['max_drawdown'] * 100:>8.1f}%"
            f"{p['alpha'] * 100:>8.1f}%{p['trade_count']:>8}{win:>9}"
        )
    print("=" * 78)
    print(
        "Alpha = strategy CAGR - SPY CAGR. Equal-weight portfolio across the "
        "watchlist.\nResults written to "
        f"{out_path}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
