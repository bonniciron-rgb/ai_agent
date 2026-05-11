"""Standalone A1 backtest validation script.

Fetches ~2 years of daily close prices via yfinance, bypasses bars_from_db
(which requires a populated DB), and runs the backtest engine directly.

Usage:
    python scripts/run_a1_backtest.py

Outputs JSON metrics to stdout.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_agent.backtest.engine import run_backtest
from ai_agent.backtest.metrics import equity_from_benchmark
from ai_agent.signals.sector_rs import SectorRelativeStrengthSignal
from ai_agent.signals.strategy_adapter import SignalStrategy

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Basket definition ──────────────────────────────────────────────────────────
SECTOR_MAP = {
    # XLK - Technology
    "AAPL": "XLK",
    "MSFT": "XLK",
    "GOOGL": "XLK",
    # XLF - Financials
    "JPM": "XLF",
    "BAC": "XLF",
    "GS": "XLF",
    # XLE - Energy
    "XOM": "XLE",
    "CVX": "XLE",
    # XLV - Health Care
    "JNJ": "XLV",
    "PFE": "XLV",
    "UNH": "XLV",
    # XLP - Consumer Staples
    "KO": "XLP",
    "PEP": "XLP",
    "PG": "XLP",
    # XLY - Consumer Discretionary
    "AMZN": "XLY",
    "HD": "XLY",
    "TSLA": "XLY",
}

ETFS = sorted(set(SECTOR_MAP.values()))
BENCHMARK = "SPY"
ALL_SYMBOLS = sorted(SECTOR_MAP.keys())

# ── Date range: ~2 years ending today ─────────────────────────────────────────
END = date(2026, 5, 11)
START = END - timedelta(days=730)  # 2 years


def fetch_prices(tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    """Download OHLCV from yfinance for all tickers at once."""
    logger.info("Downloading %d tickers from %s to %s ...", len(tickers), start, end)
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
            # Keep standard columns; drop NaN rows
            cols = [c for c in ["open", "high", "low", "close", "volume"] if c in sub.columns]
            if "adj close" in sub.columns:
                sub = sub.rename(columns={"adj close": "adj_close"})
            sub = sub[cols].dropna()
            result[sym.upper()] = sub
        except Exception as exc:
            logger.warning("Could not extract %s: %s", sym, exc)
    return result


def main() -> dict:
    # 1. Download stock + ETF data
    all_tickers = ALL_SYMBOLS + ETFS + [BENCHMARK]
    price_data = fetch_prices(all_tickers, START, END)

    # 2. Build sector_prices dict: ETF ticker → pd.Series of daily close
    sector_prices: dict[str, pd.Series] = {}
    for etf in ETFS:
        if etf in price_data and not price_data[etf].empty:
            # Convert DatetimeIndex → date objects to match runner convention
            s = price_data[etf]["close"].copy()
            s.index = pd.to_datetime(s.index).date
            sector_prices[etf] = s
            logger.info("ETF %s: %d bars", etf, len(s))
        else:
            logger.warning("No data for ETF %s", etf)

    # SPY for fallback / benchmark
    if BENCHMARK in price_data:
        s = price_data[BENCHMARK]["close"].copy()
        s.index = pd.to_datetime(s.index).date
        sector_prices[BENCHMARK] = s

    # 3. Instantiate signal with real sector prices
    signal = SectorRelativeStrengthSignal(
        sector_map=SECTOR_MAP,
        sector_prices=sector_prices,
        lookback=20,
        threshold=0.02,
    )

    # 4. Run per-symbol backtests
    initial_capital = 10_000.0
    per_symbol: dict[str, dict] = {}
    portfolio_equity = pd.Series(dtype="float64")
    total_trades = 0

    for sym in ALL_SYMBOLS:
        if sym not in price_data or price_data[sym].empty:
            logger.warning("No data for %s — skipping", sym)
            continue

        df = price_data[sym].copy()
        df.index = pd.to_datetime(df.index)
        # Filter to start/end window
        df = df[(df.index.date >= START) & (df.index.date <= END)]
        if len(df) < 50:
            logger.warning("Window too small for %s (%d bars) — skipping", sym, len(df))
            continue

        strategy = SignalStrategy(
            signal=signal,
            symbol=sym,
            entry_threshold=0.3,
            exit_threshold=0.0,
            holding_days=5,
        )
        result = run_backtest(df, strategy, symbol=sym, initial_capital=initial_capital)

        from ai_agent.backtest.metrics import summary as metrics_summary

        sym_summary = metrics_summary(result.equity_curve, result.trades)
        per_symbol[sym] = {
            "sharpe": round(sym_summary.get("sharpe", 0.0) or 0.0, 4),
            "cagr": round(sym_summary.get("cagr", 0.0) or 0.0, 4),
            "max_drawdown": round(sym_summary.get("max_drawdown", 0.0) or 0.0, 4),
            "win_rate": round(sym_summary.get("win_rate", 0.0) or 0.0, 4),
            "trades": len(result.trades),
        }
        total_trades += len(result.trades)
        logger.info(
            "%s: sharpe=%.2f cagr=%.2f%% trades=%d",
            sym,
            per_symbol[sym]["sharpe"],
            per_symbol[sym]["cagr"] * 100,
            per_symbol[sym]["trades"],
        )

        # Equal-weight portfolio
        normalized = result.equity_curve / initial_capital
        if portfolio_equity.empty:
            portfolio_equity = normalized
        else:
            portfolio_equity = portfolio_equity.add(normalized, fill_value=1.0)

    if portfolio_equity.empty:
        logger.error("No symbols had sufficient data — aborting.")
        sys.exit(1)

    n_syms = len(per_symbol)
    portfolio_equity = (portfolio_equity / n_syms) * initial_capital

    # 5. Benchmark (SPY buy-and-hold)
    bench_df = price_data.get(BENCHMARK, pd.DataFrame())
    if bench_df.empty:
        logger.error("No SPY benchmark data")
        sys.exit(1)
    bench_close = bench_df["close"].copy()
    bench_close.index = pd.to_datetime(bench_close.index)
    bench_close = bench_close[(bench_close.index.date >= START) & (bench_close.index.date <= END)]
    bench_equity = equity_from_benchmark(bench_close, initial_capital=initial_capital)

    from ai_agent.backtest.metrics import summary as metrics_summary

    portfolio_metrics = metrics_summary(portfolio_equity, [], benchmark=bench_close)
    benchmark_metrics = metrics_summary(bench_equity, [])

    output = {
        "signal_name": signal.name,
        "signal_version": signal.version,
        "period": [START.isoformat(), END.isoformat()],
        "symbols": list(per_symbol.keys()),
        "data_source": "yfinance (real market data)",
        "metrics": {
            "sharpe": round(portfolio_metrics.get("sharpe") or 0.0, 4),
            "cagr": round(portfolio_metrics.get("cagr") or 0.0, 4),
            "max_drawdown": round(portfolio_metrics.get("max_drawdown") or 0.0, 4),
            "win_rate": round(portfolio_metrics.get("win_rate") or 0.0, 4),
            "alpha": round(portfolio_metrics.get("alpha") or 0.0, 4),
            "trade_count": total_trades,
        },
        "benchmark": {
            "symbol": BENCHMARK,
            "sharpe": round(benchmark_metrics.get("sharpe") or 0.0, 4),
            "cagr": round(benchmark_metrics.get("cagr") or 0.0, 4),
            "max_drawdown": round(benchmark_metrics.get("max_drawdown") or 0.0, 4),
        },
        "per_symbol": per_symbol,
    }

    print(json.dumps(output, indent=2, default=str))
    return output


if __name__ == "__main__":
    main()
