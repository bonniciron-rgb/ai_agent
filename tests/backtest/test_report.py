"""Tests for the backtest comparison report."""

import pandas as pd

from ai_agent.backtest.engine import BacktestResult
from ai_agent.backtest.report import compare_strategies, format_report


def _make_result(values: list[float], trades: list | None = None) -> BacktestResult:
    dates = pd.date_range("2020-01-02", periods=len(values), freq="B")
    equity = pd.Series(values, index=dates)
    return BacktestResult(
        symbol="X",
        equity_curve=equity,
        trades=trades or [],
        initial_capital=10_000.0,
    )


def _make_prices(values: list[float]) -> pd.Series:
    dates = pd.date_range("2020-01-02", periods=len(values), freq="B")
    return pd.Series(values, index=dates)


def test_compare_strategies_keys() -> None:
    results = {
        "LLM": _make_result([10_000, 10_500, 11_000]),
        "SMA": _make_result([10_000, 10_200, 10_400]),
    }
    out = compare_strategies(results)
    assert "strategies" in out
    assert "LLM" in out["strategies"]
    assert "SMA" in out["strategies"]


def test_compare_strategies_with_benchmark() -> None:
    results = {"LLM": _make_result([10_000, 10_500, 11_000])}
    bench = _make_prices([400.0, 410.0, 420.0])
    out = compare_strategies(results, benchmark_close=bench, initial_capital=10_000.0)
    assert "benchmark" in out
    llm = out["strategies"]["LLM"]
    assert "alpha" in llm
    assert "benchmark_total_return" in llm


def test_compare_strategies_metrics_populated() -> None:
    results = {"X": _make_result([10_000.0] * 252)}
    out = compare_strategies(results)
    m = out["strategies"]["X"]
    assert m["total_return"] == 0.0
    assert m["num_trades"] == 0
    assert m["bars"] == 252


def test_format_report_returns_string() -> None:
    results = {
        "LLM": _make_result([10_000, 10_500, 11_000]),
        "SMA": _make_result([10_000, 10_200, 10_100]),
    }
    out = compare_strategies(results)
    text = format_report(out)
    assert isinstance(text, str)
    assert "LLM" in text
    assert "SMA" in text
    assert "Sharpe" in text


def test_format_report_shows_benchmark_line() -> None:
    results = {"LLM": _make_result([10_000, 11_000])}
    bench = _make_prices([400.0, 420.0])
    out = compare_strategies(results, benchmark_close=bench)
    text = format_report(out)
    assert "buy-and-hold" in text.lower() or "benchmark" in text.lower()


def test_compare_strategies_llm_outperforms_flat_benchmark() -> None:
    strong_equity = [10_000.0 * (1.002**i) for i in range(252)]
    flat_bench = [100.0] * 252
    results = {"LLM": _make_result(strong_equity)}
    bench = _make_prices(flat_bench)
    out = compare_strategies(results, benchmark_close=bench, initial_capital=10_000.0)
    assert out["strategies"]["LLM"]["alpha"] > 0
