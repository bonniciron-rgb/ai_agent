"""Tests for LlmStrategy using ScriptedClient (no real API calls)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ai_agent.backtest.engine import run_backtest
from ai_agent.backtest.llm_strategy import LlmStrategy

# ---------------------------------------------------------------------------
# Minimal fakes (same pattern as test_runner.py)
# ---------------------------------------------------------------------------


@dataclass
class FakeUsage:
    input_tokens: int = 5
    output_tokens: int = 5
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class FakeTextBlock:
    type: str = "text"
    text: str = "Done."


@dataclass
class FakeToolUseBlock:
    type: str = "tool_use"
    id: str = "tu_1"
    name: str = "get_portfolio"
    input: dict = field(default_factory=dict)


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)


class AlwaysBuyClient:
    """Always proposes buying 5 shares of whatever is in the watchlist."""

    def create_message(self, **kwargs: Any) -> FakeResponse:
        # Extract symbol from the user message
        kwargs["messages"][0]["content"]
        symbol = kwargs.get("messages", [{}])[0].get("content", "AAPL MSFT").split()[-1]
        propose_input = {
            "symbol": symbol,
            "side": "buy",
            "quantity": 5,
            "limit_price": 150.0,
            "rationale": "Test buy signal.",
            "confidence": "medium",
        }
        return FakeResponse(
            content=[FakeToolUseBlock(name="propose_trade", id="tu_1", input=propose_input)],
            stop_reason="tool_use",
        )


class AlwaysBuyThenEndClient:
    """Two-turn: proposes trade, then ends."""

    def __init__(self) -> None:
        self._call = 0

    def create_message(self, **kwargs: Any) -> FakeResponse:
        self._call += 1
        if self._call % 2 == 1:
            return FakeResponse(
                content=[
                    FakeToolUseBlock(
                        name="propose_trade",
                        id=f"tu_{self._call}",
                        input={
                            "symbol": "AAPL",
                            "side": "buy",
                            "quantity": 3,
                            "limit_price": 150.0,
                            "rationale": "Strong trend.",
                            "confidence": "high",
                        },
                    )
                ],
                stop_reason="tool_use",
            )
        return FakeResponse(content=[FakeTextBlock()], stop_reason="end_turn")


class NeverTradesClient:
    """Always ends with no proposals."""

    def create_message(self, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(content=[FakeTextBlock(text="No trades.")], stop_reason="end_turn")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(n: int = 250) -> pd.DataFrame:
    closes = np.linspace(100, 200, n)
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1,
            "low": closes - 1,
            "close": closes,
            "volume": [100_000] * n,
        },
        index=dates,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_llm_strategy_no_trades_when_client_holds() -> None:
    df = _make_df()
    strat = LlmStrategy(df, "AAPL", client=NeverTradesClient(), shares_per_trade=5)
    result = run_backtest(df, strat, symbol="AAPL", initial_capital=10_000.0)
    assert len(result.trades) == 0
    assert abs(result.equity_curve.iloc[-1] - 10_000.0) < 1e-6


def test_llm_strategy_generates_buy_on_proposal() -> None:
    df = _make_df()
    strat = LlmStrategy(
        df, "AAPL", client=AlwaysBuyThenEndClient(), shares_per_trade=3, call_every=50
    )
    result = run_backtest(df, strat, symbol="AAPL", initial_capital=10_000.0)
    buys = [t for t in result.trades if t.side == "buy"]
    assert len(buys) >= 1


def test_llm_strategy_call_every_limits_api_calls() -> None:
    """With call_every=50, agent is invoked ~5 times for 250-bar series."""
    call_count = 0

    class CountingClient:
        def create_message(self, **_kw: Any) -> FakeResponse:
            nonlocal call_count
            call_count += 1
            return FakeResponse(content=[FakeTextBlock()], stop_reason="end_turn")

    df = _make_df(250)
    strat = LlmStrategy(df, "AAPL", client=CountingClient(), call_every=50)
    run_backtest(df, strat, symbol="AAPL")
    # 250 bars / call_every=50 → 5 agent calls
    assert call_count == 5


def test_llm_strategy_reset_clears_bar_counter() -> None:
    df = _make_df(10)
    strat = LlmStrategy(df, "AAPL", client=NeverTradesClient())
    strat._bar_counter = 999
    strat.reset()
    assert strat._bar_counter == 0


def test_llm_strategy_equity_curve_length_matches_bars() -> None:
    df = _make_df(100)
    strat = LlmStrategy(df, "AAPL", client=NeverTradesClient(), call_every=10)
    result = run_backtest(df, strat, symbol="AAPL")
    assert len(result.equity_curve) == len(df)
