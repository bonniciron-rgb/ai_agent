"""Backtest comparison report.

compare_strategies() takes a mapping of {label: BacktestResult} plus an
optional benchmark price series and returns a nested dict with per-strategy
metrics and relative comparisons against the benchmark.

format_report() renders the dict as a human-readable text table suitable
for logging or Telegram messages.
"""

from __future__ import annotations

import pandas as pd

from ai_agent.backtest.metrics import equity_from_benchmark, summary


def compare_strategies(
    results: dict[str, object],
    *,
    benchmark_close: pd.Series | None = None,
    initial_capital: float = 10_000.0,
) -> dict:
    """Compute per-strategy metrics and optional benchmark comparison.

    Parameters
    ----------
    results:
        Mapping of display label → BacktestResult.
    benchmark_close:
        Raw price series for the benchmark (e.g. SPY).  Used as buy-and-hold.
    initial_capital:
        Starting capital used to normalise the benchmark.

    Returns
    -------
    Dict with keys:
    - ``strategies``: dict of label → metrics dict
    - ``benchmark``: benchmark metrics dict (if provided)
    """
    benchmark_equity: pd.Series | None = None
    if benchmark_close is not None and not benchmark_close.empty:
        benchmark_equity = equity_from_benchmark(benchmark_close, initial_capital=initial_capital)

    strategies_out: dict[str, dict] = {}
    for label, result in results.items():
        strategies_out[label] = summary(
            result.equity_curve,
            result.trades,
            benchmark=benchmark_equity,
        )
        strategies_out[label]["initial_capital"] = result.initial_capital

    out: dict = {"strategies": strategies_out}
    if benchmark_equity is not None:
        out["benchmark"] = summary(benchmark_equity, [])

    return out


def format_report(comparison: dict) -> str:
    """Render a comparison dict as a plain-text table."""
    lines: list[str] = ["=== Backtest Report ===\n"]

    strategies = comparison.get("strategies", {})
    bench = comparison.get("benchmark")

    row_labels = [
        ("total_return", "Total return", _pct),
        ("cagr", "CAGR", _pct),
        ("sharpe", "Sharpe ratio", _f2),
        ("max_drawdown", "Max drawdown", _pct),
        ("volatility", "Volatility", _pct),
        ("win_rate", "Win rate", _pct),
        ("num_trades", "# trades", _int),
        ("alpha", "Alpha vs bench", _pct),
    ]

    col_width = max((len(k) for k in strategies), default=10) + 2
    header = f"{'Metric':<22}" + "".join(f"{k:>{col_width}}" for k in strategies)
    lines.append(header)
    lines.append("-" * len(header))

    for key, label, fmt in row_labels:
        row = f"{label:<22}"
        for metrics in strategies.values():
            val = metrics.get(key)
            row += f"{fmt(val):>{col_width}}"
        lines.append(row)

    if bench:
        lines.append("")
        lines.append(
            f"Benchmark (buy-and-hold): total return {_pct(bench.get('total_return'))}"
            f"  Sharpe {_f2(bench.get('sharpe'))}"
            f"  Max DD {_pct(bench.get('max_drawdown'))}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:+.1f}%"


def _f2(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v:.2f}"


def _int(v: int | float | None) -> str:
    if v is None:
        return "N/A"
    return str(int(v))
