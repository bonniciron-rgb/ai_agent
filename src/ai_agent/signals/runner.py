"""Backtest a Signal across a list of symbols and produce aggregated metrics."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlmodel import Session

from ai_agent.backtest.engine import run_backtest
from ai_agent.backtest.metrics import equity_from_benchmark, summary
from ai_agent.db.engine import get_engine
from ai_agent.db.models import SignalBacktest
from ai_agent.loop.bar_store import bars_from_db
from ai_agent.signals.base import Signal
from ai_agent.signals.strategy_adapter import SignalStrategy

logger = logging.getLogger(__name__)


def _inject_earnings_events(signal: Signal, symbols: list[str], ref_date: date) -> None:
    """Fetch historical earnings from Finnhub and inject into a PostEarningsDriftSignal.

    No-op for any other signal type.  Mutates *signal.earnings_events* in place so
    the runner does not need to know which symbols are required before construction.

    The look-back passed to Finnhub is ``lookback_window_days`` taken directly from
    the signal so we fetch exactly as much history as the signal will consume.
    """
    # Import here to avoid a circular import; pead imports signals.base, not runner.
    from ai_agent.signals.pead import EarningsEvent, PostEarningsDriftSignal

    if not isinstance(signal, PostEarningsDriftSignal):
        return
    if signal.earnings_events:
        # Caller pre-populated earnings_events (e.g. in tests) — trust them, nothing to do.
        return

    import os
    from datetime import timedelta

    from ai_agent.data.base import DataSourceError
    from ai_agent.data.finnhub_source import FinnhubSource

    api_key = os.environ.get("FINNHUB_API_KEY", "")
    settings_key: str = ""
    try:
        from ai_agent.settings import get_settings

        settings_key = get_settings().finnhub_api_key.get_secret_value()
    except Exception:
        pass

    resolved_key = api_key or settings_key
    if not resolved_key:
        logger.warning(
            "FINNHUB_API_KEY not set — PostEarningsDriftSignal earnings_events will be empty"
        )
        return

    source = FinnhubSource(resolved_key)
    lookback_days = signal.lookback_window_days
    start = ref_date - timedelta(days=lookback_days)

    injected: dict[str, list[EarningsEvent]] = {}
    for sym in symbols:
        try:
            raw_events = source.earnings_calendar(sym, start=start, end=ref_date)
        except DataSourceError as exc:
            logger.warning("Finnhub earnings fetch failed for %s: %s", sym, exc)
            continue

        processed: list[EarningsEvent] = []
        for ev in raw_events:
            actual = ev.eps_actual
            consensus = ev.eps_estimate
            if actual is None or consensus is None:
                continue
            if consensus == 0:
                logger.debug(
                    "Skipping %s earnings on %s: consensus EPS is zero", sym, ev.event_date
                )
                continue
            surprise_pct = (actual - consensus) / abs(consensus)
            processed.append(
                EarningsEvent(
                    announcement_date=ev.event_date,
                    actual_eps=actual,
                    consensus_eps=consensus,
                    surprise_pct=surprise_pct,
                )
            )
        injected[sym] = processed
        logger.info(
            "Injected %d earnings events for %s (lookback %d days)",
            len(processed),
            sym,
            lookback_days,
        )

    signal.earnings_events = injected


def _inject_sector_prices(signal: Signal, days_back: int, ref_date: date) -> None:
    """Fetch sector ETF price series from DB and inject into a SectorRelativeStrengthSignal.

    No-op for any other signal type.  Mutates *signal.sector_prices* in place so
    the runner does not need to know which ETFs are required before construction.
    """
    # Import here to avoid a circular import; sector_rs imports signals.base, not runner.
    from ai_agent.signals.sector_rs import SectorRelativeStrengthSignal

    if not isinstance(signal, SectorRelativeStrengthSignal):
        return
    if signal.sector_prices:
        # Caller pre-populated sector_prices — trust them, nothing to do.
        return

    # Collect unique ETF tickers that appear in sector_map, plus the default ETF.
    etf_tickers: set[str] = set(signal.sector_map.values())
    etf_tickers.add(signal.default_etf)

    injected: dict[str, pd.Series] = {}
    for etf in etf_tickers:
        bars = bars_from_db(etf, days_back=days_back, ref_date=ref_date)
        if not bars:
            logger.warning(
                "No DB bars found for sector ETF %s — signal will fall back to flat", etf
            )
            continue
        injected[etf] = pd.Series({b.trading_date: float(b.close) for b in bars}).sort_index()
        logger.info("Injected %d price rows for sector ETF %s", len(injected[etf]), etf)

    signal.sector_prices = injected


@dataclass
class SignalBacktestSummary:
    signal_name: str
    signal_version: str
    period_start: date
    period_end: date
    symbols: list[str]
    benchmark_symbol: str

    sharpe: float | None
    cagr: float | None
    max_drawdown: float | None
    win_rate: float | None
    alpha: float | None
    benchmark_sharpe: float | None
    benchmark_cagr: float | None
    trade_count: int

    per_symbol: dict[str, dict] = field(default_factory=dict)


def _bars_to_dataframe(bars) -> pd.DataFrame:
    """Convert a BarSeries to an OHLCV DataFrame indexed by trading_date."""
    return (
        pd.DataFrame(
            [
                {
                    "trading_date": b.trading_date,
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                }
                for b in bars
            ]
        )
        .set_index("trading_date")
        .sort_index()
    )


def backtest_signal(
    signal: Signal,
    *,
    symbols: list[str],
    start: date,
    end: date,
    benchmark_symbol: str = "SPY",
    initial_capital: float = 10_000.0,
    entry_threshold: float = 0.3,
    exit_threshold: float = 0.0,
    holding_days: int = 5,
    days_back: int = 750,  # ~3 years of OHLCV
) -> SignalBacktestSummary:
    """Backtest signal across symbols, return aggregated portfolio metrics."""

    # Wire sector ETF prices into the signal if it needs them and they weren't pre-loaded.
    _inject_sector_prices(signal, days_back=days_back, ref_date=end)
    # Wire earnings events into the signal if it needs them and they weren't pre-loaded.
    _inject_earnings_events(signal, symbols=symbols, ref_date=end)

    per_symbol: dict[str, dict] = {}
    portfolio_equity = pd.Series(dtype="float64")
    total_trades = 0

    for sym in symbols:
        bars = bars_from_db(sym, days_back=days_back, ref_date=end)
        if not bars or len(bars) < 200:
            logger.warning("Insufficient bars for %s — skipping", sym)
            continue

        df = _bars_to_dataframe(bars)
        df = df[(df.index >= start) & (df.index <= end)]
        if len(df) < 50:
            logger.warning("Window too small for %s — skipping", sym)
            continue

        strategy = SignalStrategy(
            signal=signal,
            symbol=sym,
            entry_threshold=entry_threshold,
            exit_threshold=exit_threshold,
            holding_days=holding_days,
        )
        result = run_backtest(
            df,
            strategy,
            symbol=sym,
            initial_capital=initial_capital,
        )

        sym_summary = summary(result.equity_curve, result.trades)
        per_symbol[sym] = {
            "sharpe": sym_summary.get("sharpe"),
            "cagr": sym_summary.get("cagr"),
            "max_drawdown": sym_summary.get("max_drawdown"),
            "win_rate": sym_summary.get("win_rate"),
            "trades": len(result.trades),
        }
        total_trades += len(result.trades)

        # Equal-weight portfolio by averaging per-symbol equity curves
        if portfolio_equity.empty:
            portfolio_equity = result.equity_curve / initial_capital
        else:
            portfolio_equity = portfolio_equity.add(
                result.equity_curve / initial_capital,
                fill_value=1.0,
            )

    if portfolio_equity.empty:
        return SignalBacktestSummary(
            signal_name=signal.name,
            signal_version=signal.version,
            period_start=start,
            period_end=end,
            symbols=symbols,
            benchmark_symbol=benchmark_symbol,
            sharpe=None,
            cagr=None,
            max_drawdown=None,
            win_rate=None,
            alpha=None,
            benchmark_sharpe=None,
            benchmark_cagr=None,
            trade_count=0,
            per_symbol={},
        )

    portfolio_equity = portfolio_equity / max(len(per_symbol), 1)  # average across N symbols
    portfolio_equity = portfolio_equity * initial_capital

    # Benchmark
    bench_bars = bars_from_db(benchmark_symbol, days_back=days_back, ref_date=end)
    bench_close = pd.Series({b.trading_date: float(b.close) for b in bench_bars}).sort_index()
    bench_close = bench_close[(bench_close.index >= start) & (bench_close.index <= end)]
    bench_equity = equity_from_benchmark(bench_close, initial_capital=initial_capital)

    portfolio_metrics = summary(portfolio_equity, [], benchmark=bench_close)
    benchmark_metrics = summary(bench_equity, [])

    return SignalBacktestSummary(
        signal_name=signal.name,
        signal_version=signal.version,
        period_start=start,
        period_end=end,
        symbols=list(per_symbol.keys()),
        benchmark_symbol=benchmark_symbol,
        sharpe=portfolio_metrics.get("sharpe"),
        cagr=portfolio_metrics.get("cagr"),
        max_drawdown=portfolio_metrics.get("max_drawdown"),
        win_rate=portfolio_metrics.get("win_rate"),
        alpha=portfolio_metrics.get("alpha"),
        benchmark_sharpe=benchmark_metrics.get("sharpe"),
        benchmark_cagr=benchmark_metrics.get("cagr"),
        trade_count=total_trades,
        per_symbol=per_symbol,
    )


def save_backtest_result(
    result: SignalBacktestSummary,
    *,
    notes: str | None = None,
    engine=None,
) -> SignalBacktest:
    """Persist a backtest result to the SignalBacktest table.  Returns the inserted row."""
    eng = engine or get_engine()
    row = SignalBacktest(
        signal_name=result.signal_name,
        signal_version=result.signal_version,
        period_start=result.period_start,
        period_end=result.period_end,
        symbols_json=json.dumps(result.symbols),
        benchmark_symbol=result.benchmark_symbol,
        sharpe=result.sharpe,
        cagr=result.cagr,
        max_drawdown=result.max_drawdown,
        win_rate=result.win_rate,
        alpha=result.alpha,
        benchmark_sharpe=result.benchmark_sharpe,
        benchmark_cagr=result.benchmark_cagr,
        trade_count=result.trade_count,
        notes=notes,
    )
    with Session(eng) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row
