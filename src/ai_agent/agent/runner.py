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

## Tiered routing (m18)
When ``tiered=True`` (the default, controlled by ``LLM_TIERED`` env var):
  - Stage 1 (Haiku): cheap screening pass → shortlist of up to N tickers.
  - Stage 2 (Opus): deep decision pass only on shortlisted tickers.
When ``tiered=False``, the original single-pass behaviour is preserved.

## Prompt caching
For both passes, static system-prompt blocks carry
``cache_control: {"type": "ephemeral"}`` so Anthropic caches them across
calls within the TTL, reducing cost to ~10 % of normal input pricing.
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

# Default model IDs (overridden by Settings / env vars in daily_loop.py)
DEFAULT_SCREENING_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_DECISION_MODEL = "claude-opus-4-7"

# Decision-pass system prompt with prompt-cache marker on the static block.
# Anthropic caches all content up to and including the block carrying
# cache_control, so the dynamic user message (today's watchlist) is NOT cached.
_DECISION_SYSTEM_CACHED_BLOCKS: list[dict] = [
    {
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    },
]


# ---------------------------------------------------------------------------
# Thin protocol so tests can inject a fake without the real anthropic SDK
# ---------------------------------------------------------------------------


class AnthropicClientProtocol(Protocol):
    def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str | list[dict],
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
    # Reasoning-audit fields (m16 — preserved)
    prompt_messages: list[dict] = field(default_factory=list)
    response_text: str = ""
    model: str = MODEL
    # m18: per-pass token breakdown
    screening_input_tokens: int = 0
    screening_output_tokens: int = 0
    screening_cache_creation_tokens: int = 0
    screening_cache_read_tokens: int = 0
    decision_input_tokens: int = 0
    decision_output_tokens: int = 0
    decision_cache_creation_tokens: int = 0
    decision_cache_read_tokens: int = 0


# ---------------------------------------------------------------------------
# Real Anthropic adapter (imported lazily to keep CI fast)
# ---------------------------------------------------------------------------


class _AnthropicAdapter:
    """Thin wrapper around the real anthropic.Anthropic SDK.

    Supports both the legacy string ``system`` arg and the new list-of-blocks
    form required for prompt caching.
    """

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
        system: str | list[dict],
        tools: list[dict],
        messages: list[dict],
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        return self._client.messages.create(**kwargs)


# ---------------------------------------------------------------------------
# Screening-pass adapter
# ---------------------------------------------------------------------------


class _ScreeningClientAdapter:
    """Adapts AnthropicClientProtocol → ScreeningClientProtocol.

    Screening does NOT use tools (keeps the cheap pass cheap), so we forward
    create_message calls without the tools kwarg.
    """

    def __init__(self, client: AnthropicClientProtocol) -> None:
        self._client = client

    def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: list[dict],
        messages: list[dict],
    ) -> Any:
        # Pass tools=[] so the real adapter omits the tools param
        return self._client.create_message(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=[],
            messages=messages,
        )


# ---------------------------------------------------------------------------
# Decision-pass core loop (Stage 2 or single-pass legacy)
# ---------------------------------------------------------------------------


def _run_decision_pass(
    shortlist: list[str],
    toolbox: Toolbox,
    *,
    client: AnthropicClientProtocol,
    model: str,
    max_tokens: int,
) -> AgentResult:
    """Run the full tool-use agent loop against *shortlist* tickers only."""
    result = AgentResult(model=model)
    messages: list[dict] = [{"role": "user", "content": build_user_message(shortlist)}]
    result.prompt_messages = list(messages)

    for iteration in range(MAX_ITERATIONS):
        result.iterations = iteration + 1

        response = client.create_message(
            model=model,
            max_tokens=max_tokens,
            system=_DECISION_SYSTEM_CACHED_BLOCKS,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Accumulate token usage
        if hasattr(response, "usage"):
            u = response.usage
            it = getattr(u, "input_tokens", 0)
            ot = getattr(u, "output_tokens", 0)
            crt = getattr(u, "cache_read_input_tokens", 0)
            cwt = getattr(u, "cache_creation_input_tokens", 0)
            result.input_tokens += it
            result.output_tokens += ot
            result.cache_read_tokens += crt
            result.cache_write_tokens += cwt
            result.decision_input_tokens += it
            result.decision_output_tokens += ot
            result.decision_cache_creation_tokens += cwt
            result.decision_cache_read_tokens += crt

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

    # Capture full conversation for reasoning audit (m16)
    result.prompt_messages = messages
    result.response_text = _extract_text_response(messages)

    # Collect proposals from toolbox
    result.proposals = [_to_proposal(p) for p in toolbox._proposals if _to_proposal(p) is not None]
    return result


# ---------------------------------------------------------------------------
# Tiered two-pass implementation
# ---------------------------------------------------------------------------


def _held_symbols(toolbox: Toolbox) -> set[str]:
    """Plain symbols of currently-held positions, for screening exclusion.

    Position keys are full T212 tickers (e.g. ``AAPL_US_EQ``); the watchlist
    uses plain symbols, so the venue suffix is stripped.
    """
    held: set[str] = set()
    try:
        pf = toolbox.get_portfolio({})
        positions = pf.get("positions", {}) if isinstance(pf, dict) else {}
        for raw in positions:
            plain = str(raw).split("_")[0].upper()
            if plain:
                held.add(plain)
    except Exception as exc:
        logger.warning("Could not read portfolio for screening exclusion: %s", exc)
    return held


def _run_tiered(
    watchlist: list[str],
    toolbox: Toolbox,
    *,
    client: AnthropicClientProtocol,
    screening_model: str,
    decision_model: str,
    max_tokens: int,
    shortlist_max: int,
) -> AgentResult:
    """Stage 1: Haiku screens the watchlist (held names excluded). Stage 2: Opus decides."""
    from ai_agent.agent.screening import run_screening

    screening_client = _ScreeningClientAdapter(client)

    # Exclude already-held tickers up front: the no-re-entry rule would
    # disqualify them in the decision pass anyway, so letting them consume
    # screening shortlist slots starves genuine new candidates.
    held = _held_symbols(toolbox)
    screening_universe = [s for s in watchlist if s.upper() not in held]
    if len(screening_universe) < len(watchlist):
        logger.info(
            "Screening universe: %d/%d watchlist symbols (%d already held, excluded)",
            len(screening_universe),
            len(watchlist),
            len(watchlist) - len(screening_universe),
        )

    symbol_context: dict[str, str] = {}
    for sym in screening_universe:
        try:
            feats = toolbox.get_features({"symbol": sym})
            symbol_context[sym] = json.dumps(feats, default=str)[:600]
        except Exception as exc:
            logger.warning("Could not fetch features for %s during screening: %s", sym, exc)

    screening_result = run_screening(
        screening_universe,
        client=screening_client,  # type: ignore[arg-type]
        model=screening_model,
        max_tokens=1024,
        max_tickers=shortlist_max,
        symbol_context=symbol_context or None,
    )

    # Build result seeded with screening token counts
    result = AgentResult(
        model=screening_model,
        screening_input_tokens=screening_result.input_tokens,
        screening_output_tokens=screening_result.output_tokens,
        screening_cache_creation_tokens=screening_result.cache_creation_tokens,
        screening_cache_read_tokens=screening_result.cache_read_tokens,
        input_tokens=screening_result.input_tokens,
        output_tokens=screening_result.output_tokens,
        cache_read_tokens=screening_result.cache_read_tokens,
        cache_write_tokens=screening_result.cache_creation_tokens,
    )

    used_fallback = False
    if not screening_result.shortlist:
        logger.info(
            "Screening returned empty shortlist — running decision pass on the "
            "un-held watchlist (%d symbols)",
            len(screening_universe),
        )
        used_fallback = True
        shortlist = list(screening_universe)
    else:
        shortlist = [e.symbol for e in screening_result.shortlist]
    logger.info("Decision pass on shortlist (%d symbols): %s", len(shortlist), shortlist)

    decision = _run_decision_pass(
        shortlist=shortlist,
        toolbox=toolbox,
        client=client,
        model=decision_model,
        max_tokens=max_tokens,
    )

    # Merge decision counts into aggregate result
    result.model = decision_model
    result.proposals = decision.proposals
    result.iterations = decision.iterations
    result.stop_reason = "screening_empty_fallback" if used_fallback else decision.stop_reason
    result.prompt_messages = decision.prompt_messages
    result.response_text = decision.response_text
    result.input_tokens += decision.input_tokens
    result.output_tokens += decision.output_tokens
    result.cache_read_tokens += decision.cache_read_tokens
    result.cache_write_tokens += decision.cache_write_tokens
    result.decision_input_tokens = decision.decision_input_tokens
    result.decision_output_tokens = decision.decision_output_tokens
    result.decision_cache_creation_tokens = decision.decision_cache_creation_tokens
    result.decision_cache_read_tokens = decision.decision_cache_read_tokens

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_agent(
    watchlist: list[str],
    toolbox: Toolbox,
    *,
    client: AnthropicClientProtocol | None = None,
    model: str = MODEL,
    max_tokens: int = 4096,
    api_key: str | None = None,
    # Tiered routing parameters (m18)
    tiered: bool = True,
    screening_model: str = DEFAULT_SCREENING_MODEL,
    decision_model: str = DEFAULT_DECISION_MODEL,
    shortlist_max: int = 5,
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
        Claude model ID used in legacy single-pass mode (tiered=False).
    max_tokens:
        Maximum output tokens per API call.
    api_key:
        Anthropic API key; falls back to ``ANTHROPIC_API_KEY`` env var.
    tiered:
        When True, run Haiku screening → Opus decision two-pass flow.
        When False, run the original single-pass with *model*.
    screening_model:
        Model for Stage-1 screening (ignored when tiered=False).
    decision_model:
        Model for Stage-2 decision (ignored when tiered=False).
    shortlist_max:
        Maximum shortlist size forwarded from Stage 1 to Stage 2.
    """
    if client is None:
        client = _AnthropicAdapter(api_key=api_key)

    if tiered:
        return _run_tiered(
            watchlist=watchlist,
            toolbox=toolbox,
            client=client,
            screening_model=screening_model,
            decision_model=decision_model,
            max_tokens=max_tokens,
            shortlist_max=shortlist_max,
        )

    # Legacy single-pass (LLM_TIERED=false)
    return _run_decision_pass(
        shortlist=watchlist,
        toolbox=toolbox,
        client=client,
        model=model,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text_response(messages: list[dict]) -> str:
    """Extract a readable summary of all assistant text blocks from the conversation."""
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if hasattr(block, "type") and block.type == "text":
                    parts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n\n".join(parts)


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
