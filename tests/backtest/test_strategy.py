"""Tests for SmaCrossStrategy and EmaBreakoutStrategy."""

import numpy as np
import pandas as pd

from ai_agent.backtest.strategy import EmaBreakoutStrategy, SmaCrossStrategy


def _make_close(values: list[float]) -> pd.Series:
    dates = pd.date_range("2020-01-02", periods=len(values), freq="B")
    return pd.Series(values, index=dates)


def _make_row(close: float, open_: float | None = None) -> pd.Series:
    o = open_ if open_ is not None else close
    return pd.Series(
        {"open": o, "high": close + 1, "low": close - 1, "close": close, "volume": 1e5}
    )


# ---------- SmaCrossStrategy ----------


def test_sma_cross_no_signal_during_warmup() -> None:
    """No signal before the slow SMA is defined."""
    closes = _make_close([100.0] * 210)
    strat = SmaCrossStrategy(closes, fast=50, slow=200)
    strat.reset()

    # First 200 bars are warm-up for slow SMA
    for i in range(200):
        date = closes.index[i]
        sig = strat.on_bar(date=date, row=_make_row(100.0), position=0, cash=10_000.0)
        assert sig == 0, f"Expected 0 at bar {i}, got {sig}"


def test_sma_cross_golden_cross_triggers_buy() -> None:
    """A rising price series should eventually cross fast SMA above slow SMA → buy."""
    # Build a series: flat for 200 bars, then rising steeply so fast > slow
    flat = [100.0] * 200
    rising = list(np.linspace(100.0, 400.0, 60))
    closes = _make_close(flat + rising)
    strat = SmaCrossStrategy(closes, fast=50, slow=200, shares_per_trade=5)
    strat.reset()

    buy_signals = []
    for i, date in enumerate(closes.index):
        row = _make_row(float(closes.iloc[i]))
        sig = strat.on_bar(date=date, row=row, position=0, cash=10_000.0)
        if sig > 0:
            buy_signals.append(i)

    assert len(buy_signals) >= 1, "Expected at least one buy signal on golden cross"


def test_sma_cross_death_cross_triggers_sell() -> None:
    """After a golden cross, a falling price should produce a death cross → sell.

    Data is constructed so a golden cross definitely precedes a death cross:
    - 200 bars flat at 100 → both SMAs settle at 100
    - 70 bars at 500 → fast SMA (50) rockets to 500 while slow SMA lags → golden cross
    - 120 bars at 30 → fast SMA (50) collapses to 30 while slow SMA lags high → death cross
    """
    flat = [100.0] * 200
    high = [500.0] * 70
    low = [30.0] * 120
    closes = _make_close(flat + high + low)
    strat = SmaCrossStrategy(closes, fast=50, slow=200, shares_per_trade=5)
    strat.reset()

    position = 0
    buy_signals = []
    sell_signals = []
    for i, date in enumerate(closes.index):
        row = _make_row(float(closes.iloc[i]))
        sig = strat.on_bar(date=date, row=row, position=position, cash=10_000.0)
        if sig > 0:
            position += sig
            buy_signals.append(i)
        elif sig < 0:
            sell_signals.append(i)
            position += sig  # sig is negative

    assert len(buy_signals) >= 1, "Expected at least one buy signal on golden cross"
    assert len(sell_signals) >= 1, "Expected at least one sell signal on death cross"


def test_sma_cross_reset_clears_state() -> None:
    closes = _make_close([100.0] * 260)
    strat = SmaCrossStrategy(closes, fast=50, slow=200)
    strat.reset()
    strat._prev_above = True  # artificially set
    strat.reset()
    assert strat._prev_above is None


def test_sma_cross_full_allocation_when_no_fixed_shares() -> None:
    """When shares_per_trade is None, strategy buys as many shares as cash allows."""
    up = list(np.linspace(80.0, 200.0, 120))
    down_flat = [80.0] * 100
    up2 = list(np.linspace(80.0, 160.0, 60))
    closes = _make_close(down_flat + up2 + up)

    strat = SmaCrossStrategy(closes, fast=50, slow=200, shares_per_trade=None)
    strat.reset()

    cash = 5_000.0
    for i, date in enumerate(closes.index):
        row = _make_row(float(closes.iloc[i]))
        sig = strat.on_bar(date=date, row=row, position=0, cash=cash)
        if sig > 0:
            price = float(closes.iloc[i])
            assert sig >= int(cash // price), "Should try to use all cash"
            break


# ---------- EmaBreakoutStrategy ----------


def test_ema_breakout_no_signal_during_warmup() -> None:
    closes = _make_close([100.0] * 25)
    strat = EmaBreakoutStrategy(closes, period=20)
    strat.reset()

    for i in range(20):
        date = closes.index[i]
        sig = strat.on_bar(date=date, row=_make_row(100.0), position=0, cash=10_000.0)
        assert sig == 0


def test_ema_breakout_buy_when_price_crosses_above() -> None:
    """Price crossing above EMA should trigger a buy."""
    flat = [100.0] * 30
    spike = [200.0] * 30
    closes = _make_close(flat + spike)
    strat = EmaBreakoutStrategy(closes, period=20, shares_per_trade=3)
    strat.reset()

    buys = []
    for i, date in enumerate(closes.index):
        row = _make_row(float(closes.iloc[i]))
        sig = strat.on_bar(date=date, row=row, position=0, cash=10_000.0)
        if sig > 0:
            buys.append(i)

    assert len(buys) >= 1
