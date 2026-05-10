"""Stage-1 screening pass: uses Haiku to rank the full watchlist cheaply.

Returns a shortlist of up to ``max_tickers`` symbols for Stage-2 deep analysis.

The screening prompt is intentionally lean — no tool calls, just a JSON
response so we keep tool-definition tokens out of the cheap pass.

Prompt caching is applied to the static blocks (system + output schema
description) so the cached prefix is reused on every daily call.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SCREENING_SYSTEM_PROMPT = """\
You are a quantitative equity screening assistant. Your sole job is to quickly \
rank a watchlist of US equities by their conviction level for same-day trading \
and return a shortlist of the most promising symbols.

## What to consider
- Momentum / trend strength (you will be given recent price action context)
- Potential catalysts (earnings, macro, sector moves)
- Risk/reward skew

## Output format (strict JSON — no other text)
Respond with ONLY valid JSON in this exact shape:
{
  "shortlist": [
    {"symbol": "AAPL", "rationale": "1-sentence reason"},
    ...
  ]
}

Rules:
- Include at most MAX_TICKERS entries (the caller will enforce the cap).
- Rank highest-conviction symbols first.
- Symbols NOT worth deep analysis should be omitted entirely.
- If NO symbols are worth analysing today, return {"shortlist": []}.
- Do NOT include limit/stop math — that is Stage 2's job.
"""

SCREENING_OUTPUT_SCHEMA = """\
The JSON output schema (already described above) must be strictly followed.
Return ONLY the JSON object — no markdown fences, no commentary.
"""


def build_screening_user_message(watchlist: list[str]) -> str:
    tickers = ", ".join(watchlist) if watchlist else "(empty)"
    return (
        f"Watchlist ({len(watchlist)} symbols): {tickers}\n\n"
        "Rank these symbols by same-day trading conviction. "
        "Return only your JSON shortlist."
    )


# ---------------------------------------------------------------------------
# Protocol (matches AnthropicClientProtocol in runner.py)
# ---------------------------------------------------------------------------


class ScreeningClientProtocol(Protocol):
    def create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system: list[dict],
        messages: list[dict],
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class ShortlistEntry:
    symbol: str
    rationale: str


@dataclass
class ScreeningResult:
    shortlist: list[ShortlistEntry] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


# ---------------------------------------------------------------------------
# Core screening function
# ---------------------------------------------------------------------------


def run_screening(
    watchlist: list[str],
    *,
    client: ScreeningClientProtocol,
    model: str,
    max_tokens: int = 1024,
    max_tickers: int = 5,
) -> ScreeningResult:
    """Call Haiku with the full watchlist; return the shortlist.

    Uses prompt caching on the static system blocks so the cached prefix
    is reused on every subsequent call within the cache TTL.
    """
    result = ScreeningResult()

    # Build system prompt with cache_control on the last static block.
    # The Anthropic API caches everything up to and including the block
    # that carries cache_control: ephemeral.
    system_blocks: list[dict] = [
        {
            "type": "text",
            "text": SCREENING_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": SCREENING_OUTPUT_SCHEMA,
            "cache_control": {"type": "ephemeral"},
        },
    ]

    messages = [
        {"role": "user", "content": build_screening_user_message(watchlist)},
    ]

    try:
        response = client.create_message(
            model=model,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=messages,
        )
    except Exception as exc:
        logger.error("Screening API call failed: %s", exc)
        return result

    # Accumulate token usage
    if hasattr(response, "usage"):
        u = response.usage
        result.input_tokens += getattr(u, "input_tokens", 0)
        result.output_tokens += getattr(u, "output_tokens", 0)
        result.cache_creation_tokens += getattr(u, "cache_creation_input_tokens", 0)
        result.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0)

    # Parse JSON from the response
    raw_text = _extract_text(response)
    if not raw_text:
        logger.warning("Screening response had no text content — empty shortlist")
        return result

    try:
        parsed = json.loads(raw_text)
        entries_raw = parsed.get("shortlist", [])
        if not isinstance(entries_raw, list):
            raise ValueError("shortlist must be a list")

        shortlist: list[ShortlistEntry] = []
        for item in entries_raw[:max_tickers]:
            sym = str(item.get("symbol", "")).upper().strip()
            rationale = str(item.get("rationale", ""))
            if sym and sym in {s.upper() for s in watchlist}:
                shortlist.append(ShortlistEntry(symbol=sym, rationale=rationale))

        result.shortlist = shortlist
        logger.info(
            "Screening shortlist (%d/%d): %s",
            len(shortlist),
            len(watchlist),
            [e.symbol for e in shortlist],
        )
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Could not parse screening JSON (%s): %r", exc, raw_text[:200])

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text(response: Any) -> str:
    """Pull the first text block from an Anthropic response."""
    content = getattr(response, "content", [])
    if isinstance(content, list):
        for block in content:
            t = getattr(block, "type", None)
            if t == "text":
                return getattr(block, "text", "")
            # SimpleNamespace / dict fallback
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    if isinstance(content, str):
        return content
    return ""
