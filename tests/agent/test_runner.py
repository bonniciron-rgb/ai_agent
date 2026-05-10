"""Tests for the agentic runner loop using a fake Anthropic client."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ai_agent.agent.proposals import TradeProposal
from ai_agent.agent.runner import AgentResult, run_agent
from ai_agent.agent.tools import Toolbox
from ai_agent.db.models import OrderSide

# ---------------------------------------------------------------------------
# Fake Anthropic SDK objects
# ---------------------------------------------------------------------------


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class FakeTextBlock:
    type: str = "text"
    text: str = "Analysis complete."


@dataclass
class FakeToolUseBlock:
    type: str = "tool_use"
    id: str = "tu_001"
    name: str = "get_portfolio"
    input: dict = field(default_factory=dict)


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)


class ScriptedClient:
    """Returns pre-defined responses in order; raises on unexpected extra calls."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self._index = 0

    def create_message(self, **_kwargs: Any) -> FakeResponse:
        if self._index >= len(self._responses):
            raise AssertionError("Unexpected extra API call")
        resp = self._responses[self._index]
        self._index += 1
        return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_toolbox() -> Toolbox:
    def fake_propose(inputs: dict) -> TradeProposal:
        return TradeProposal(
            symbol=inputs["symbol"],
            side=OrderSide(inputs["side"]),
            quantity=int(inputs["quantity"]),
            limit_price=Decimal(str(inputs["limit_price"])),
            rationale=inputs["rationale"],
            confidence=inputs["confidence"],
        )

    return Toolbox(
        get_features=lambda i: {"regime": "trending_up", "rsi_14": 55.0, "adx_14": 28.0},
        get_news=lambda i: [{"headline": "AAPL beats earnings", "sentiment": "positive"}],
        get_portfolio=lambda i: {"cash": 50_000.0, "positions": []},
        propose_trade=fake_propose,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_end_turn_immediately_returns_empty_proposals() -> None:
    client = ScriptedClient(
        [
            FakeResponse(content=[FakeTextBlock(text="No trades today.")], stop_reason="end_turn"),
        ]
    )
    # tiered=False preserves the original single-pass behaviour
    result = run_agent(watchlist=["AAPL"], toolbox=_simple_toolbox(), client=client, tiered=False)
    assert isinstance(result, AgentResult)
    assert result.proposals == []
    assert result.iterations == 1
    assert result.stop_reason == "end_turn"


def test_single_tool_call_then_end_turn() -> None:
    """Agent calls get_portfolio once then ends."""
    client = ScriptedClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock(name="get_portfolio", id="tu_1", input={})],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[FakeTextBlock(text="Portfolio is empty. No trades.")],
                stop_reason="end_turn",
            ),
        ]
    )
    result = run_agent(watchlist=["AAPL"], toolbox=_simple_toolbox(), client=client, tiered=False)
    assert result.proposals == []
    assert result.iterations == 2


def test_propose_trade_captured() -> None:
    """Agent calls propose_trade; result appears in AgentResult.proposals."""
    propose_input = {
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 10,
        "limit_price": 175.0,
        "stop_price": 168.0,
        "rationale": "Strong uptrend, ADX=28, volume spike.",
        "confidence": "high",
    }
    client = ScriptedClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock(name="propose_trade", id="tu_2", input=propose_input)],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[FakeTextBlock(text="Proposal submitted.")],
                stop_reason="end_turn",
            ),
        ]
    )
    result = run_agent(watchlist=["AAPL"], toolbox=_simple_toolbox(), client=client, tiered=False)
    assert len(result.proposals) == 1
    p = result.proposals[0]
    assert p.symbol == "AAPL"
    assert p.side == OrderSide.buy
    assert p.quantity == 10
    assert p.confidence == "high"


def test_multiple_tool_calls_in_one_response() -> None:
    """Multiple tool_use blocks in a single response are all dispatched."""
    client = ScriptedClient(
        [
            FakeResponse(
                content=[
                    FakeToolUseBlock(name="get_portfolio", id="tu_1", input={}),
                    FakeToolUseBlock(name="get_features", id="tu_2", input={"symbol": "MSFT"}),
                ],
                stop_reason="tool_use",
            ),
            FakeResponse(
                content=[FakeTextBlock(text="Done.")],
                stop_reason="end_turn",
            ),
        ]
    )
    result = run_agent(watchlist=["MSFT"], toolbox=_simple_toolbox(), client=client, tiered=False)
    assert result.iterations == 2
    assert result.proposals == []


def test_token_usage_accumulated() -> None:
    usage1 = FakeUsage(input_tokens=100, output_tokens=50)
    usage2 = FakeUsage(input_tokens=80, output_tokens=30)
    client = ScriptedClient(
        [
            FakeResponse(
                content=[FakeToolUseBlock(name="get_portfolio", id="tu_1", input={})],
                stop_reason="tool_use",
                usage=usage1,
            ),
            FakeResponse(
                content=[FakeTextBlock()],
                stop_reason="end_turn",
                usage=usage2,
            ),
        ]
    )
    result = run_agent(watchlist=["AAPL"], toolbox=_simple_toolbox(), client=client, tiered=False)
    assert result.input_tokens == 180
    assert result.output_tokens == 80


def test_max_iterations_guard() -> None:
    """If the agent keeps calling tools, the loop exits after MAX_ITERATIONS."""
    from ai_agent.agent import runner as runner_mod

    # Override MAX_ITERATIONS to 3 for this test
    original = runner_mod.MAX_ITERATIONS
    runner_mod.MAX_ITERATIONS = 3
    try:
        infinite_tool = FakeResponse(
            content=[FakeToolUseBlock(name="get_portfolio", id="tu_1", input={})],
            stop_reason="tool_use",
        )

        # ScriptedClient would raise after script exhausted, so use a loop client
        class LoopClient:
            def create_message(self, **_kw):
                return infinite_tool

        result = run_agent(
            watchlist=["AAPL"], toolbox=_simple_toolbox(), client=LoopClient(), tiered=False
        )
        assert result.iterations == 3
    finally:
        runner_mod.MAX_ITERATIONS = original
