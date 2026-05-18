"""Tests for m18 tiered LLM routing (Haiku screening → Opus decision).

Covers:
  - Empty shortlist → Stage 2 falls back to full watchlist (not skipped)
  - Shortlist of 3 → Stage 2 runs once with exactly those 3 in context
  - cache_control header present on static system blocks for both passes
  - Cost calculation handles cache_read_tokens and cache_creation_tokens
  - Integration: full daily loop dry-run uses screening model then decision model
  - build_screening_user_message includes per-symbol context when provided
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ai_agent.agent.proposals import TradeProposal
from ai_agent.agent.runner import run_agent
from ai_agent.agent.tools import Toolbox
from ai_agent.db.models import OrderSide

# ---------------------------------------------------------------------------
# Shared fake objects
# ---------------------------------------------------------------------------


@dataclass
class FakeUsage:
    input_tokens: int = 10
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
    id: str = "tu_001"
    name: str = "get_portfolio"
    input: dict = field(default_factory=dict)


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)


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
        get_news=lambda i: [],
        get_portfolio=lambda i: {"cash": 50_000.0, "positions": []},
        propose_trade=fake_propose,
    )


# ---------------------------------------------------------------------------
# Fake client that records calls and validates model / system structure
# ---------------------------------------------------------------------------


class RecordingClient:
    """Records every create_message call for assertion in tests."""

    def __init__(self, responses: list[Any]) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses)
        self._index = 0

    def create_message(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._index >= len(self._responses):
            raise AssertionError("Unexpected extra API call")
        resp = self._responses[self._index]
        self._index += 1
        return resp


def _screening_response(shortlist: list[dict]) -> FakeResponse:
    """Return a FakeResponse whose text block contains a shortlist JSON."""
    payload = json.dumps({"shortlist": shortlist})
    return FakeResponse(content=[FakeTextBlock(text=payload)], stop_reason="end_turn")


def _decision_end_turn() -> FakeResponse:
    return FakeResponse(content=[FakeTextBlock(text="Analysis complete.")], stop_reason="end_turn")


# ---------------------------------------------------------------------------
# Test: empty shortlist → Stage 2 falls back to full watchlist
# ---------------------------------------------------------------------------


def test_empty_shortlist_falls_back_to_full_watchlist() -> None:
    """When Haiku returns an empty shortlist, Stage 2 must run on the full watchlist."""
    watchlist = ["AAPL", "MSFT", "GOOG"]
    client = RecordingClient(
        responses=[
            _screening_response([]),  # Stage 1: empty shortlist
            _decision_end_turn(),  # Stage 2 must still run
        ]
    )

    result = run_agent(
        watchlist=watchlist,
        toolbox=_simple_toolbox(),
        client=client,
        tiered=True,
        screening_model="claude-haiku-4-5-20251001",
        decision_model="claude-opus-4-7",
    )

    assert result.stop_reason == "screening_empty_fallback"
    assert result.iterations >= 1
    # Both screening and decision API calls must have been made
    assert len(client.calls) == 2
    # Decision pass user message must contain all watchlist symbols
    decision_call = client.calls[1]
    decision_user_msg = decision_call["messages"][0]["content"]
    for sym in watchlist:
        assert sym in decision_user_msg, f"{sym} must appear in fallback decision user message"


# ---------------------------------------------------------------------------
# Test: shortlist of 3 → Stage 2 runs with exactly those 3
# ---------------------------------------------------------------------------


def test_shortlist_of_3_decision_pass_uses_correct_symbols() -> None:
    """Stage 2 receives only the 3 shortlisted symbols in its user message."""
    shortlist_symbols = ["AAPL", "MSFT", "NVDA"]
    shortlist_payload = [
        {"symbol": s, "rationale": f"strong momentum in {s}"} for s in shortlist_symbols
    ]

    propose_input = {
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 5,
        "limit_price": 180.0,
        "stop_price": 172.0,
        "rationale": "Breakout above resistance.",
        "confidence": "high",
    }

    client = RecordingClient(
        responses=[
            _screening_response(shortlist_payload),  # Stage 1
            FakeResponse(
                content=[FakeToolUseBlock(name="propose_trade", id="tu_1", input=propose_input)],
                stop_reason="tool_use",
            ),  # Stage 2 iteration 1
            _decision_end_turn(),  # Stage 2 iteration 2
        ]
    )

    result = run_agent(
        watchlist=["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"],  # 5 total, 3 shortlisted
        toolbox=_simple_toolbox(),
        client=client,
        tiered=True,
        screening_model="claude-haiku-4-5-20251001",
        decision_model="claude-opus-4-7",
    )

    # Proposal captured
    assert len(result.proposals) == 1
    assert result.proposals[0].symbol == "AAPL"

    # 3 calls: 1 screening + 2 decision iterations
    assert len(client.calls) == 3

    # Decision pass user message must contain only shortlisted symbols
    decision_call = client.calls[1]
    decision_user_msg = decision_call["messages"][0]["content"]
    for sym in shortlist_symbols:
        assert sym in decision_user_msg, f"{sym} must appear in decision user message"
    # Non-shortlisted symbol must NOT appear
    assert "TSLA" not in decision_user_msg
    assert "AMZN" not in decision_user_msg


# ---------------------------------------------------------------------------
# Test: shortlist capped at shortlist_max
# ---------------------------------------------------------------------------


def test_shortlist_max_is_enforced() -> None:
    """LLM_SHORTLIST_MAX caps the shortlist even if screening returns more."""
    # Screening returns 5 symbols but max is 3
    shortlist_payload = [
        {"symbol": s, "rationale": "conviction"} for s in ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"]
    ]

    client = RecordingClient(
        responses=[
            _screening_response(shortlist_payload),  # Stage 1 returns 5
            _decision_end_turn(),  # Stage 2
        ]
    )

    run_agent(
        watchlist=["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"],
        toolbox=_simple_toolbox(),
        client=client,
        tiered=True,
        screening_model="claude-haiku-4-5-20251001",
        decision_model="claude-opus-4-7",
        shortlist_max=3,
    )

    # Decision call message should only contain 3 symbols
    decision_call = client.calls[1]
    decision_user_msg = decision_call["messages"][0]["content"]
    found = [s for s in ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN"] if s in decision_user_msg]
    assert len(found) <= 3


# ---------------------------------------------------------------------------
# Test: cache_control present on static system blocks for both passes
# ---------------------------------------------------------------------------


def test_screening_pass_system_has_cache_control() -> None:
    """The screening pass must send cache_control on the static system blocks."""
    client = RecordingClient(responses=[_screening_response([]), _decision_end_turn()])

    run_agent(
        watchlist=["AAPL"],
        toolbox=_simple_toolbox(),
        client=client,
        tiered=True,
        screening_model="claude-haiku-4-5-20251001",
        decision_model="claude-opus-4-7",
    )

    screening_call = client.calls[0]
    system = screening_call["system"]
    assert isinstance(system, list), "Screening system must be a list of blocks"
    cached_blocks = [b for b in system if b.get("cache_control") == {"type": "ephemeral"}]
    assert len(cached_blocks) >= 1, "At least one block must carry cache_control: ephemeral"


def test_decision_pass_system_has_cache_control() -> None:
    """The decision pass must send cache_control on the static system prompt block."""
    shortlist_payload = [{"symbol": "AAPL", "rationale": "momentum"}]

    client = RecordingClient(
        responses=[
            _screening_response(shortlist_payload),  # Stage 1
            _decision_end_turn(),  # Stage 2
        ]
    )

    run_agent(
        watchlist=["AAPL"],
        toolbox=_simple_toolbox(),
        client=client,
        tiered=True,
        screening_model="claude-haiku-4-5-20251001",
        decision_model="claude-opus-4-7",
    )

    decision_call = client.calls[1]
    system = decision_call["system"]
    assert isinstance(system, list), "Decision system must be a list of blocks"
    cached_blocks = [b for b in system if b.get("cache_control") == {"type": "ephemeral"}]
    assert len(cached_blocks) >= 1, "Decision system must have at least one cached block"


# ---------------------------------------------------------------------------
# Test: screening pass does NOT include tools (keeps cheap pass cheap)
# ---------------------------------------------------------------------------


def test_screening_pass_has_no_tools() -> None:
    """The screening API call must not carry tool definitions."""
    client = RecordingClient(responses=[_screening_response([]), _decision_end_turn()])

    run_agent(
        watchlist=["AAPL"],
        toolbox=_simple_toolbox(),
        client=client,
        tiered=True,
    )

    screening_call = client.calls[0]
    tools = screening_call.get("tools", [])
    assert tools == [], f"Screening call must have no tools, got {tools}"


# ---------------------------------------------------------------------------
# Test: cost calculation with cache tokens
# ---------------------------------------------------------------------------


def test_cost_calculation_haiku_with_cache_tokens() -> None:
    """Cost helper correctly accounts for cache read/write at Haiku pricing."""
    from ai_agent.agent.cost import calculate_cost_usd

    # 1000 regular input tokens + 500 cache-write + 2000 cache-read + 200 output
    cost = calculate_cost_usd(
        "claude-haiku-4-5-20251001",
        input_tokens=1000,
        output_tokens=200,
        cache_creation_tokens=500,
        cache_read_tokens=2000,
    )

    # Haiku: $1/M input, $5/M output
    # Regular input: 1000 * 1.00 / 1_000_000 = 0.001
    # Output:        200  * 5.00 / 1_000_000 = 0.001
    # Cache write:   500  * 1.00 * 1.25 / 1_000_000 = 0.000625
    # Cache read:    2000 * 1.00 * 0.10 / 1_000_000 = 0.0002
    expected = Decimal("0.001") + Decimal("0.001") + Decimal("0.000625") + Decimal("0.0002")
    assert abs(cost - expected) < Decimal("1e-6"), f"Expected ~{expected}, got {cost}"


def test_cost_calculation_opus_with_cache_tokens() -> None:
    """Cost helper correctly accounts for cache tokens at Opus pricing."""
    from ai_agent.agent.cost import calculate_cost_usd

    cost = calculate_cost_usd(
        "claude-opus-4-7",
        input_tokens=10_000,
        output_tokens=1_000,
        cache_creation_tokens=5_000,
        cache_read_tokens=20_000,
    )

    # Opus: $15/M input, $75/M output
    # Regular input: 10000 * 15 / 1_000_000 = 0.15
    # Output:        1000 * 75 / 1_000_000  = 0.075
    # Cache write:   5000 * 15 * 1.25 / 1_000_000 = 0.09375
    # Cache read:    20000 * 15 * 0.10 / 1_000_000 = 0.03
    expected = Decimal("0.15") + Decimal("0.075") + Decimal("0.09375") + Decimal("0.03")
    assert abs(cost - expected) < Decimal("1e-6"), f"Expected ~{expected}, got {cost}"


def test_cost_calculation_zero_cache_tokens() -> None:
    """Cost calculation without cache tokens is identical to pure token pricing."""
    from ai_agent.agent.cost import calculate_cost_usd

    cost_cached = calculate_cost_usd(
        "claude-haiku-4-5-20251001",
        input_tokens=1000,
        output_tokens=200,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    # 1000 * 1/M + 200 * 5/M = 0.001 + 0.001 = 0.002
    expected = Decimal("0.002")
    assert abs(cost_cached - expected) < Decimal("1e-6")


# ---------------------------------------------------------------------------
# Test: legacy single-pass mode (tiered=False)
# ---------------------------------------------------------------------------


def test_single_pass_mode_skips_screening() -> None:
    """With tiered=False, only one API call is made (no screening)."""
    client = RecordingClient(responses=[_decision_end_turn()])

    result = run_agent(
        watchlist=["AAPL", "MSFT"],
        toolbox=_simple_toolbox(),
        client=client,
        tiered=False,
        model="claude-sonnet-4-6",
    )

    assert result.proposals == []
    assert len(client.calls) == 1
    # The single call should use the provided model
    assert client.calls[0]["model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Test: token accumulation across screening + decision
# ---------------------------------------------------------------------------


def test_token_accumulation_tiered() -> None:
    """Total token counts are the sum of screening + decision tokens."""
    screening_usage = FakeUsage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=20,
        cache_read_input_tokens=10,
    )
    decision_usage = FakeUsage(
        input_tokens=500,
        output_tokens=300,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=80,
    )

    shortlist_payload = [{"symbol": "AAPL", "rationale": "strong"}]
    screening_resp = FakeResponse(
        content=[FakeTextBlock(text=json.dumps({"shortlist": shortlist_payload}))],
        stop_reason="end_turn",
        usage=screening_usage,
    )
    decision_resp = FakeResponse(
        content=[FakeTextBlock(text="Done.")],
        stop_reason="end_turn",
        usage=decision_usage,
    )

    client = RecordingClient(responses=[screening_resp, decision_resp])

    result = run_agent(
        watchlist=["AAPL", "MSFT"],
        toolbox=_simple_toolbox(),
        client=client,
        tiered=True,
        screening_model="claude-haiku-4-5-20251001",
        decision_model="claude-opus-4-7",
    )

    assert result.input_tokens == 600  # 100 + 500
    assert result.output_tokens == 350  # 50 + 300
    assert result.screening_input_tokens == 100
    assert result.screening_cache_creation_tokens == 20
    assert result.screening_cache_read_tokens == 10
    assert result.decision_input_tokens == 500
    assert result.decision_cache_read_tokens == 80


# ---------------------------------------------------------------------------
# Test: build_screening_user_message includes per-symbol context
# ---------------------------------------------------------------------------


def test_build_screening_user_message_includes_symbol_context() -> None:
    """When symbol_context is provided, each symbol appears with its context line."""
    from ai_agent.agent.screening import build_screening_user_message

    watchlist = ["AAPL", "MSFT", "GOOG"]
    symbol_context = {
        "AAPL": '{"close": 195.2, "regime": "ranging", "rsi_14": 55.0}',
        "MSFT": '{"close": 420.1, "regime": "trending_up", "rsi_14": 62.3}',
        # GOOG intentionally missing — should still appear as bare symbol
    }

    msg = build_screening_user_message(watchlist, symbol_context)

    assert 'AAPL: {"close": 195.2' in msg
    assert 'MSFT: {"close": 420.1' in msg
    assert "GOOG" in msg
    # Without context, bare symbol should still render
    assert "ranging" in msg
    assert "trending_up" in msg


def test_build_screening_user_message_no_context_backward_compatible() -> None:
    """Without symbol_context the message format is unchanged."""
    from ai_agent.agent.screening import build_screening_user_message

    msg = build_screening_user_message(["AAPL", "MSFT"])

    assert "AAPL" in msg
    assert "MSFT" in msg
    # Original compact comma-separated format
    assert "AAPL, MSFT" in msg


# ---------------------------------------------------------------------------
# Test: already-held tickers are excluded before screening
# ---------------------------------------------------------------------------


def _toolbox_holding(*tickers: str) -> Toolbox:
    """Like _simple_toolbox, but reports the given tickers as open positions.

    Position keys are full T212 tickers (e.g. AAPL_US_EQ), matching the
    real get_portfolio output.
    """
    tb = _simple_toolbox()
    positions = {f"{t}_US_EQ": "100" for t in tickers}
    tb.get_portfolio = lambda i: {"cash": 50_000.0, "positions": positions}
    return tb


def test_held_symbols_strips_venue_suffix() -> None:
    """_held_symbols returns plain symbols from full T212 position tickers."""
    from ai_agent.agent.runner import _held_symbols

    assert _held_symbols(_toolbox_holding("AAPL", "CSCO")) == {"AAPL", "CSCO"}
    assert _held_symbols(_simple_toolbox()) == set()


def test_screening_excludes_held_tickers() -> None:
    """A watchlist symbol that is already held must be dropped before screening."""
    client = RecordingClient(
        responses=[
            _screening_response([]),  # empty shortlist → fallback to un-held universe
            _decision_end_turn(),
        ]
    )

    result = run_agent(
        watchlist=["AAA", "BBB", "CCC"],
        toolbox=_toolbox_holding("BBB"),
        client=client,
        tiered=True,
        screening_model="claude-haiku-4-5-20251001",
        decision_model="claude-opus-4-7",
    )

    assert result.stop_reason == "screening_empty_fallback"
    decision_user_msg = client.calls[1]["messages"][0]["content"]
    assert "AAA" in decision_user_msg
    assert "CCC" in decision_user_msg
    assert "BBB" not in decision_user_msg
