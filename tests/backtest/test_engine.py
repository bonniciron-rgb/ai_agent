"""Tests for the bar-by-bar backtest engine."""

import pandas as pd
import pytest

from ai_agent.backtest.engine import run_backtest


def _make_df(closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    """Build a minimal OHLCV frame from close prices."""
    n = len(closes)
    opens_ = opens if opens is not None else closes
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": opens_,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [100_000] * n,
        },
        index=dates,
    )


class HoldStrategy:
    """Never trades."""

    def reset(self) -> None:
        pass

    def on_bar(self, *, date, row, position, cash) -> int:
        return 0


class BuyOnBarOneStrategy:
    """Buys 10 shares on the first bar, never sells."""

    def reset(self) -> None:
        self._fired = False

    def on_bar(self, *, date, row, position, cash) -> int:
        if not self._fired:
            self._fired = True
            return 10
        return 0


class BuyThenSellStrategy:
    """Buys 5 shares on bar 0, sells all on bar 2."""

    def reset(self) -> None:
        self._bar = 0

    def on_bar(self, *, date, row, position, cash) -> int:
        self._bar += 1
        if self._bar == 1:
            return 5
        if self._bar == 3 and position > 0:
            return -position
        return 0


def test_empty_df_raises() -> None:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    with pytest.raises(ValueError):
        run_backtest(df, HoldStrategy(), symbol="X")


def test_hold_strategy_equity_equals_initial() -> None:
    df = _make_df([100.0] * 50)
    result = run_backtest(df, HoldStrategy(), symbol="X", initial_capital=10_000.0)
    assert abs(result.equity_curve.iloc[-1] - 10_000.0) < 1e-6
    assert len(result.trades) == 0


def test_buy_increases_equity_on_rising_prices() -> None:
    closes = list(range(100, 150))  # 50 bars, rising
    df = _make_df(closes)
    result = run_backtest(df, BuyOnBarOneStrategy(), symbol="X", initial_capital=10_000.0)
    assert result.equity_curve.iloc[-1] > 10_000.0
    assert len(result.trades) == 1
    assert result.trades[0].side == "buy"
    assert result.trades[0].qty == 10


def test_buy_then_sell_round_trip() -> None:
    closes = [100.0, 105.0, 110.0, 115.0, 120.0]
    df = _make_df(closes, opens=closes)
    result = run_backtest(df, BuyThenSellStrategy(), symbol="X", initial_capital=10_000.0)
    buys = [t for t in result.trades if t.side == "buy"]
    sells = [t for t in result.trades if t.side == "sell"]
    assert len(buys) == 1
    assert len(sells) == 1
    # Position is flat at end; equity > initial due to rising prices
    assert result.trades[-1].position_after == 0
    assert result.equity_curve.iloc[-1] > 10_000.0


def test_equity_curve_length_matches_bars() -> None:
    df = _make_df([100.0] * 30)
    result = run_backtest(df, HoldStrategy(), symbol="X")
    assert len(result.equity_curve) == len(df)


def test_cannot_afford_buy_with_no_cash() -> None:
    """If cash is insufficient, no trade should be executed."""
    df = _make_df([1_000_000.0] * 10)  # each share costs 1M
    result = run_backtest(df, BuyOnBarOneStrategy(), symbol="X", initial_capital=100.0)
    # Can't afford even 1 share at 1M; no trades
    assert len(result.trades) == 0


def test_commission_reduces_final_equity() -> None:
    closes = list(range(100, 200))
    df = _make_df(closes)
    no_comm = run_backtest(
        df, BuyOnBarOneStrategy(), symbol="X", initial_capital=10_000.0, commission=0.0
    )
    with_comm = run_backtest(
        df, BuyOnBarOneStrategy(), symbol="X", initial_capital=10_000.0, commission=0.01
    )
    assert no_comm.equity_curve.iloc[-1] > with_comm.equity_curve.iloc[-1]
