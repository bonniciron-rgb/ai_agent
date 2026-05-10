"""LLM cost calculation helpers for tiered routing (m18).

Pricing (per million tokens, as of May 2026):
  Haiku 4.5   — input $1.00,  output $5.00
  Opus  4.7   — input $15.00, output $75.00
  Cache write — 1.25x input price
  Cache read  — 0.10x input price
"""

from __future__ import annotations

from decimal import Decimal

# Per-million-token prices in USD
_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
    },
    "claude-opus-4-7": {
        "input": 15.00,
        "output": 75.00,
    },
    # Fallback / legacy
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
    },
}

_DEFAULT_INPUT_PRICE = 3.00
_DEFAULT_OUTPUT_PRICE = 15.00

# Cache multipliers (Anthropic standard)
_CACHE_WRITE_MULTIPLIER = 1.25
_CACHE_READ_MULTIPLIER = 0.10


def _get_prices(model: str) -> tuple[float, float]:
    """Return (input_price_per_M, output_price_per_M) for *model*.

    Falls back to Sonnet-class pricing for unknown models.
    """
    # Match on prefix so minor version bumps still resolve
    for key, prices in _PRICING.items():
        if model.startswith(key) or key.startswith(model):
            return prices["input"], prices["output"]
    return _DEFAULT_INPUT_PRICE, _DEFAULT_OUTPUT_PRICE


def calculate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> Decimal:
    """Return the USD cost for a single API call.

    Parameters
    ----------
    model:
        Model ID string (e.g. ``"claude-haiku-4-5-20251001"``).
    input_tokens:
        Regular (non-cached) input tokens.
    output_tokens:
        Output (completion) tokens.
    cache_creation_tokens:
        Tokens written to the cache (charged at 1.25x input price).
    cache_read_tokens:
        Tokens read from the cache (charged at 0.10x input price).
    """
    input_price, output_price = _get_prices(model)

    cost = (
        input_tokens * input_price / 1_000_000
        + output_tokens * output_price / 1_000_000
        + cache_creation_tokens * input_price * _CACHE_WRITE_MULTIPLIER / 1_000_000
        + cache_read_tokens * input_price * _CACHE_READ_MULTIPLIER / 1_000_000
    )
    return Decimal(str(round(cost, 8)))
