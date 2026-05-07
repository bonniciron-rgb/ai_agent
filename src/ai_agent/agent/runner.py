"""Agentic loop: sends messages to Claude, dispatches tool calls, loops until done.

Usage
-----
from ai_agent.agent.runner import run_agent
from ai_agent.agent.tools import Toolbox

toolbox = Toolbox(
    get_features=...,
    get_news=...,
    get_portfolio=...,
    propose_trade=...,
)
result = run_agent(watchlist=["AAPL", "MSFT"], toolbox=toolbox)
print(result.proposals)

The Anthropic client is constructed lazily so the module can be imported in
tests without the `anthropic` package or API key present.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from ai_agent.agent.prompts import SYSTEM_PROMPT, build_user_message
from ai_agent.agent.proposals import TradeProposal
from ai_agent.agent.tools import TOOL_SCHEMAS, Toolbox
from ai_agent.db.models import OrderSide

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20  # hard cap to prevent runaway loops
MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Thin protocol so tests can inject a fake without the real anthropic SDK
# ---------------------------------------------------------------------------


class AnthropicClientProtocol(Protocol):
    def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        tools: list[dict],
        messages: list[dict],
    ) -> Any: ...


@dataclass
class AgentResult:
    proposals: list[TradeProposal] = field(default_factory=list)
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    stop_reason: str = ""


# ---------------------------------------------------------------------------
# Real Anthropic adapter (imported lazily to keep CI fast)
# ---------------------------------------------------------------------------


class _AnthropicAdapter:
    """Thin wrapper around the real anthropic.Anthropic SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError("Install the 'agent' extra: pip install 'ai-agent[agent]'") from exc
        self._client = anthropic.Anthropic(api_key=api_key)

    def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        tools: list[dict],
        messages: list[dict],
    ) -> Any:
        return self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )


# ---------------------------------------------------------------------------
# Core agentic loop
# ---------------------------------------------------------------------------


def run_agent(
    watchlist: list[str],
    toolbox: Toolbox,
    *,
    client: AnthropicClientProtocol | None = None,
    model: str = MODEL,
    max_tokens: int = 4096,
    api_key: str | None = None,
) -> AgentResult:
    """Run the trading agent over *watchlist* and return proposals.

    Parameters
    ----------
    watchlist:
        Ticker symbols to analyse.
    toolbox:
        Callable implementations for each tool the agent can invoke.
    client:
        Anthropic client (injected in tests; defaults to real SDK adapter).
    model:
        Claude model ID.
    max_tokens:
        Maximum output tokens per API call.
    api_key:
        Anthropic API key; falls back to ``ANTHROPIC_API_KEY`` env var.
    """
    if client is None:
        client = _AnthropicAdapter(api_key=api_key)

    result = AgentResult()
    messages: list[dict] = [{"role": "user", "content": build_user_message(watchlist)}]

    for iteration in range(MAX_ITERATIONS):
        result.iterations = iteration + 1

        response = client.create_message(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Accumulate token usage
        if hasattr(response, "usage"):
            u = response.usage
            result.input_tokens += getattr(u, "input_tokens", 0)
            result.output_tokens += getattr(u, "output_tokens", 0)
            result.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0)
            result.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0)

        result.stop_reason = response.stop_reason

        # Append assistant turn
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            logger.warning("Unexpected stop_reason %r — halting", response.stop_reason)
            break

        # Dispatch all tool calls in this response
        tool_results: list[dict] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            logger.debug("Tool call: %s(%s)", block.name, block.input)
            raw_result = toolbox.dispatch(block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _serialise(raw_result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    # Collect proposals from toolbox
    result.proposals = [_to_proposal(p) for p in toolbox._proposals if _to_proposal(p) is not None]
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialise(obj: Any) -> str:
    """Convert a tool result to a JSON string for the API message."""
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, default=_json_default)
    except Exception:
        return str(obj)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def _to_proposal(raw: Any) -> TradeProposal | None:
    """Convert a propose_trade tool result into a typed TradeProposal."""
    if isinstance(raw, TradeProposal):
        return raw
    if isinstance(raw, dict):
        try:
            return TradeProposal(
                symbol=raw["symbol"],
                side=OrderSide(raw["side"]),
                quantity=int(raw["quantity"]),
                limit_price=Decimal(str(raw["limit_price"])),
                stop_price=Decimal(str(raw["stop_price"])) if raw.get("stop_price") else None,
                rationale=raw["rationale"],
                confidence=raw["confidence"],
            )
        except (KeyError, ValueError) as exc:
            logger.warning("Could not parse proposal %r: %s", raw, exc)
    return None
