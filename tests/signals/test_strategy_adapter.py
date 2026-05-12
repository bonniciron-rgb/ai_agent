"""Tests for SignalStrategy and FractionalSignalStrategy — Signal-to-Strategy adapters."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ai_agent.signals.base import SignalContext, SignalResult
from ai_agent.signals.strategy_adapter import FractionalSignalStrategy, SignalStrategy


class _StubSignal:
    name = "stub"
    version = "v1"

    def __init__(self, scores: list[float]):
        self.scores = list(scores)

    def compute(self, ctx: SignalContext) -> SignalResult:
        score = self.scores.pop(0) if self.scores else 0.0
        return SignalResult(score=score)


def _make_row(close: float = 100.0) -> pd.Series:
    return pd.Series(
        {"open": close, "high": close, "low": close, "close": close, "volume": 1_000_000}
    )


def _ts(day: int) -> pd.Timestamp:
    return pd.Timestamp(date(2020, 1, 1) + timedelta(days=day))


def _feed_bars(strategy: SignalStrategy, n: int, score_override: float | None = None) -> list[int]:
    """Feed n bars and collect signals."""
    signals = []
    for i in range(n):
        sig = strategy.on_bar(date=_ts(i), row=_make_row(), position=0, cash=10_000.0)
        signals.append(sig)
    return signals


class TestSignalStrategyWarmup:
    def test_warmup_returns_zero(self):
        stub = _StubSignal([1.0] * 100)
        strategy = SignalStrategy(signal=stub, symbol="TEST", warmup_bars=50)
        strategy.reset()
        signals = _feed_bars(strategy, 49)
        assert all(s == 0 for s in signals)

    def test_first_bar_after_warmup_can_trigger_entry(self):
        stub = _StubSignal([1.0] * 100)
        strategy = SignalStrategy(signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3)
        strategy.reset()
        signals = []
        for i in range(50):
            sig = strategy.on_bar(
                date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0
            )
            signals.append(sig)
        # First 49 are warmup, bar 50 triggers
        assert all(s == 0 for s in signals[:49])
        assert signals[49] > 0


class TestSignalStrategyEntry:
    def test_enters_on_strong_score(self):
        stub = _StubSignal([1.0] * 100)
        strategy = SignalStrategy(signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3)
        strategy.reset()
        for i in range(49):
            strategy.on_bar(date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0)
        # 50th bar — score=1.0 >= threshold 0.3 → should buy
        sig = strategy.on_bar(date=_ts(49), row=_make_row(close=100.0), position=0, cash=10_000.0)
        assert sig == 100  # 10000 // 100

    def test_holds_below_threshold(self):
        # score=0.1 is below entry_threshold=0.3
        stub = _StubSignal([0.1] * 100)
        strategy = SignalStrategy(signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3)
        strategy.reset()
        for i in range(49):
            strategy.on_bar(date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0)
        sig = strategy.on_bar(date=_ts(49), row=_make_row(close=100.0), position=0, cash=10_000.0)
        assert sig == 0


class TestSignalStrategyExit:
    def _warmup_strategy(self, strategy: SignalStrategy) -> None:
        strategy.reset()
        for i in range(49):
            strategy.on_bar(date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0)

    def test_exits_on_bearish_flip(self):
        # compute() is only called after warmup (bar 50+), so the stub scores
        # map 1:1 to post-warmup bars.  First post-warmup bar: entry (score=1.0),
        # second post-warmup bar: bearish flip (score=-0.5).
        stub = _StubSignal([1.0, -0.5] + [0.0] * 20)
        strategy = SignalStrategy(
            signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3, exit_threshold=0.0
        )
        strategy.reset()
        for i in range(49):
            strategy.on_bar(date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0)
        # bar 50: score=1.0, position=0 → enter (return 100 shares)
        strategy.on_bar(date=_ts(49), row=_make_row(close=100.0), position=0, cash=10_000.0)
        # bar 51: score=-0.5, position=100 → exit
        sig = strategy.on_bar(date=_ts(50), row=_make_row(close=100.0), position=100, cash=0.0)
        assert sig == -100

    def test_exits_after_holding_days(self):
        # holding_days=3, bullish score throughout; should exit after 3 held days.
        # compute() is only called post-warmup, so scores map 1:1 to post-warmup bars.
        stub = _StubSignal([1.0] * 20)
        strategy = SignalStrategy(
            signal=stub,
            symbol="TEST",
            warmup_bars=50,
            entry_threshold=0.3,
            exit_threshold=0.0,
            holding_days=3,
        )
        strategy.reset()
        for i in range(49):
            strategy.on_bar(date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0)
        # bar 50: score=1.0, position=0 → enter
        strategy.on_bar(date=_ts(49), row=_make_row(close=100.0), position=0, cash=10_000.0)
        # bars 51-52: held_days increments to 1, 2 — not yet at holding_days=3
        sig_51 = strategy.on_bar(date=_ts(50), row=_make_row(close=100.0), position=100, cash=0.0)
        sig_52 = strategy.on_bar(date=_ts(51), row=_make_row(close=100.0), position=100, cash=0.0)
        # bar 53: held_days reaches 3 → exit
        sig_53 = strategy.on_bar(date=_ts(52), row=_make_row(close=100.0), position=100, cash=0.0)
        assert sig_51 == 0
        assert sig_52 == 0
        assert sig_53 == -100


class TestSignalStrategyReset:
    def test_reset_clears_bars_and_held_days(self):
        stub = _StubSignal([1.0] * 200)
        strategy = SignalStrategy(signal=stub, symbol="TEST", warmup_bars=50, holding_days=3)
        strategy.reset()
        for i in range(55):
            strategy.on_bar(date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0)
        # Simulate having held days
        strategy._held_days = 2

        strategy.reset()
        assert strategy._bars_seen == []
        assert strategy._held_days == 0

    def test_reset_restarts_warmup(self):
        stub = _StubSignal([1.0] * 200)
        strategy = SignalStrategy(signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3)
        strategy.reset()
        # Fill warmup
        for i in range(50):
            strategy.on_bar(date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0)

        # After reset, next 49 bars should be warmup again
        strategy.reset()
        signals = []
        for i in range(49):
            sig = strategy.on_bar(
                date=_ts(i), row=_make_row(close=100.0), position=0, cash=10_000.0
            )
            signals.append(sig)
        assert all(s == 0 for s in signals)


# ── FractionalSignalStrategy ──────────────────────────────────────────────────


class TestFractionalWarmup:
    def test_warmup_returns_zero(self):
        stub = _StubSignal([1.0] * 100)
        strat = FractionalSignalStrategy(signal=stub, symbol="TEST", warmup_bars=50)
        strat.reset()
        for i in range(49):
            sig = strat.on_bar(date=_ts(i), row=_make_row(), position=0, cash=10_000.0)
            assert sig == 0


class TestFractionalEntry:
    def _warmup(self, strat: FractionalSignalStrategy) -> None:
        strat.reset()
        for i in range(49):
            strat.on_bar(date=_ts(i), row=_make_row(100.0), position=0, cash=10_000.0)

    def test_score_one_deploys_full_cash(self):
        stub = _StubSignal([1.0] * 100)
        strat = FractionalSignalStrategy(
            signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3
        )
        self._warmup(strat)
        sig = strat.on_bar(date=_ts(49), row=_make_row(100.0), position=0, cash=10_000.0)
        # score=1.0, alloc=1.0, cash=10000, close=100 → 100 shares
        assert sig == 100

    def test_score_half_deploys_half_cash(self):
        stub = _StubSignal([0.5] * 100)
        strat = FractionalSignalStrategy(
            signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3
        )
        self._warmup(strat)
        sig = strat.on_bar(date=_ts(49), row=_make_row(100.0), position=0, cash=10_000.0)
        # score=0.5, alloc=0.5, cash=10000, close=100 → 50 shares
        assert sig == 50

    def test_score_one_third_deploys_one_third(self):
        stub = _StubSignal([1.0 / 3] * 100)
        strat = FractionalSignalStrategy(
            signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3
        )
        self._warmup(strat)
        sig = strat.on_bar(date=_ts(49), row=_make_row(100.0), position=0, cash=10_000.0)
        # score≈0.333, alloc≈0.333, cash=10000, close=100 → 33 shares
        assert sig == 33

    def test_below_threshold_no_entry(self):
        stub = _StubSignal([0.2] * 100)
        strat = FractionalSignalStrategy(
            signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3
        )
        self._warmup(strat)
        sig = strat.on_bar(date=_ts(49), row=_make_row(100.0), position=0, cash=10_000.0)
        assert sig == 0

    def test_max_alloc_caps_deployment(self):
        stub = _StubSignal([1.0] * 100)
        strat = FractionalSignalStrategy(
            signal=stub, symbol="TEST", warmup_bars=50, entry_threshold=0.3, max_alloc=0.5
        )
        self._warmup(strat)
        sig = strat.on_bar(date=_ts(49), row=_make_row(100.0), position=0, cash=10_000.0)
        # score=1.0 but max_alloc=0.5 → 50 shares max
        assert sig == 50


class TestFractionalExit:
    def _enter(self, strat: FractionalSignalStrategy) -> None:
        strat.reset()
        for i in range(49):
            strat.on_bar(date=_ts(i), row=_make_row(100.0), position=0, cash=10_000.0)
        strat.on_bar(date=_ts(49), row=_make_row(100.0), position=0, cash=10_000.0)

    def test_exits_after_holding_days(self):
        stub = _StubSignal([1.0] * 200)
        strat = FractionalSignalStrategy(signal=stub, symbol="TEST", warmup_bars=50, holding_days=3)
        self._enter(strat)
        strat.on_bar(date=_ts(50), row=_make_row(100.0), position=50, cash=5_000.0)
        strat.on_bar(date=_ts(51), row=_make_row(100.0), position=50, cash=5_000.0)
        sig = strat.on_bar(date=_ts(52), row=_make_row(100.0), position=50, cash=5_000.0)
        assert sig == -50

    def test_exits_on_score_drop(self):
        stub = _StubSignal([1.0, -0.5] + [0.0] * 20)
        strat = FractionalSignalStrategy(
            signal=stub, symbol="TEST", warmup_bars=50, exit_threshold=0.0, holding_days=20
        )
        self._enter(strat)
        sig = strat.on_bar(date=_ts(50), row=_make_row(100.0), position=50, cash=5_000.0)
        assert sig == -50


class TestFractionalReset:
    def test_reset_clears_state(self):
        stub = _StubSignal([1.0] * 200)
        strat = FractionalSignalStrategy(signal=stub, symbol="TEST", warmup_bars=50)
        strat.reset()
        for i in range(55):
            strat.on_bar(date=_ts(i), row=_make_row(), position=0, cash=10_000.0)
        strat.reset()
        assert strat._bars_seen == []
        assert strat._held_days == 0
