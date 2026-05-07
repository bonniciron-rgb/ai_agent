"""LLM-powered parser: converts raw Telegram text into structured ParsedSignal objects.

Uses Claude Haiku with prompt caching on the system prompt so repeated calls
within a single ingest batch share the cached context (≈90% token discount on
the instruction block).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from ai_agent.external_signals.models import ParsedSignal

logger = logging.getLogger(__name__)

# Cached across all parse_message() calls in a batch.
_SYSTEM_PROMPT = """\
You are a trading signal extractor. Given a Telegram message from a retail trading channel, extract any actionable trade ideas mentioned.

Return a JSON array of objects. Each object may contain:
- "symbol"      (string, required)  — ticker in uppercase, e.g. "AAPL"
- "side"        (string, required)  — one of "buy", "sell", "watch"
- "entry_price" (number, optional)  — suggested entry price
- "stop_price"  (number, optional)  — stop-loss price
- "target_price"(number, optional)  — profit-target price
- "conviction"  (string, optional)  — one of "high", "medium", "low"
- "notes"       (string, optional)  — one-sentence rationale

Rules:
1. Return [] if the message has no actionable trade idea (general chat, memes, news without direction, channel admin posts).
2. Do not invent prices that are not explicitly stated.
3. If a ticker is mentioned but direction is unclear, use side="watch".
4. Return only valid JSON — no markdown fences, no explanation outside the array.
"""


class _ParserClientProtocol(Protocol):
    def messages(self) -> Any: ...


def parse_message(
    text: str,
    *,
    model: str = "claude-haiku-4-5-20251001",
    client: Any | None = None,
    api_key: str | None = None,
) -> list[ParsedSignal]:
    """Parse one Telegram message and return a (possibly empty) list of signals.

    ``client`` is the raw ``anthropic.Anthropic`` instance.  Injected in tests
    to avoid hitting the real API.
    """
    if client is None:
        client = _build_client(api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": text}],
        )
        raw_text = _extract_text(response)
        data = json.loads(raw_text)
        if not isinstance(data, list):
            return []
        signals: list[ParsedSignal] = []
        for item in data:
            try:
                signals.append(ParsedSignal(**item))
            except Exception as exc:
                logger.warning("Skipping malformed signal item %r: %s", item, exc)
        return signals
    except json.JSONDecodeError as exc:
        logger.warning("LLM returned non-JSON for message: %s", exc)
        return []
    except Exception as exc:
        logger.warning("parse_message failed: %s", exc)
        return []


def _extract_text(response: Any) -> str:
    if hasattr(response, "content"):
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
    return "[]"


def _build_client(api_key: str | None) -> Any:
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError("Install the 'agent' extra: pip install 'ai_agent[agent]'") from exc
    return anthropic.Anthropic(api_key=api_key)
