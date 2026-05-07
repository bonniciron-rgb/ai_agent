"""Tests for backtest metrics."""

import pandas as pd
import pytest

from ai_agent.backtest.engine import Trade
from ai_agent.backtest.metrics import (
    cagr,
    equity_from_benchmark,
    max_drawdown,
    sharpe_ratio,
    summary,
    total_return,
    win_rate,
)


def _equity(values: list[float]) -> pd.Series:
    dates = pd.date_range("2020-01-02", periods=len(values), freq="B")
    return pd.Series(values, index=dates, name="equity")


def _trade(side: str, price: float) -> Trade:
    return Trade(
        date=pd.Timestamp("2020-01-02"),
        symbol="X",
        side=side,
        qty=1,
        price=price,
        cash_after=0.0,
        position_after=0,
    )


# --- total_return ---


def test_total_return_zero_for_flat() -> None:
    eq = _equity([100.0] * 252)
    assert total_return(eq) == pytest.approx(0.0)


def test_total_return_positive() -> None:
    eq = _equity([100.0, 110.0])
    assert total_return(eq) == pytest.approx(0.1)


def test_total_return_negative() -> None:
    eq = _equity([100.0, 90.0])
    assert total_return(eq) == pytest.approx(-0.1)


def test_total_return_single_bar() -> None:
    assert total_return(_equity([100.0])) == 0.0


# --- cagr ---


def test_cagr_flat_series() -> None:
    eq = _equity([100.0] * 252)  # exactly 1 year flat
    assert cagr(eq) == pytest.approx(0.0, abs=1e-6)


def test_cagr_doubles_in_one_year() -> None:
    eq = _equity([100.0, 200.0] + [200.0] * 250)  # 252 bars, doubles at bar 2
    # cagr should be positive
    assert cagr(eq) > 0.0


# --- max_drawdown ---


def test_max_drawdown_no_drawdown() -> None:
    eq = _equity([100.0, 110.0, 120.0, 130.0])
    assert max_drawdown(eq) == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown_50_pct() -> None:
    eq = _equity([100.0, 50.0])
    assert max_drawdown(eq) == pytest.approx(-0.5)


def test_max_drawdown_recovers() -> None:
    eq = _equity([100.0, 120.0, 60.0, 130.0])
    # Peak = 120, trough = 60 → drawdown = -50 %
    assert max_drawdown(eq) == pytest.approx(-0.5)


# --- sharpe_ratio ---


def test_sharpe_flat_returns_zero() -> None:
    eq = _equity([100.0] * 252)
    assert sharpe_ratio(eq) == 0.0


def test_sharpe_positive_for_uptrend() -> None:
    vals = [100.0 * (1.001**i) for i in range(252)]
    eq = _equity(vals)
    assert sharpe_ratio(eq) > 0.0


def test_sharpe_single_bar() -> None:
    assert sharpe_ratio(_equity([100.0])) == 0.0


# --- win_rate ---


def test_win_rate_all_winners() -> None:
    trades = [_trade("buy", 100.0), _trade("sell", 110.0)]
    assert win_rate(trades) == pytest.approx(1.0)


def test_win_rate_all_losers() -> None:
    trades = [_trade("buy", 100.0), _trade("sell", 90.0)]
    assert win_rate(trades) == pytest.approx(0.0)


def test_win_rate_mixed() -> None:
    trades = [
        _trade("buy", 100.0),
        _trade("sell", 110.0),  # win
        _trade("buy", 100.0),
        _trade("sell", 90.0),  # loss
    ]
    assert win_rate(trades) == pytest.approx(0.5)


def test_win_rate_no_closed_trades() -> None:
    trades = [_trade("buy", 100.0)]  # open, no sell
    assert win_rate(trades) == 0.0


def test_win_rate_empty() -> None:
    assert win_rate([]) == 0.0


# --- equity_from_benchmark ---


def test_equity_from_benchmark_grows_with_price() -> None:
    prices = _equity([100.0, 110.0, 120.0])
    bench = equity_from_benchmark(prices, initial_capital=10_000.0)
    assert bench.iloc[0] == pytest.approx(10_000.0)
    assert bench.iloc[-1] == pytest.approx(12_000.0)


def test_equity_from_benchmark_empty() -> None:
    result = equity_from_benchmark(pd.Series(dtype=float))
    assert result.empty


# --- summary ---


def test_summary_keys_present() -> None:
    eq = _equity([100.0, 105.0, 110.0, 108.0, 115.0])
    trades = [_trade("buy", 100.0), _trade("sell", 110.0)]
    result = summary(eq, trades)
    for key in (
        "total_return",
        "cagr",
        "sharpe",
        "max_drawdown",
        "volatility",
        "win_rate",
        "num_trades",
    ):
        assert key in result


def test_summary_with_benchmark_adds_alpha() -> None:
    eq = _equity([100.0, 110.0, 120.0])
    bench = _equity([100.0, 102.0, 104.0])
    result = summary(eq, [], benchmark=bench)
    assert "alpha" in result
    assert "benchmark_total_return" in result
