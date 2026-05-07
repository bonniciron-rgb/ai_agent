"""Tool schemas and dispatch for the Claude trading agent.

Tools follow the Anthropic tool-use spec:
  {"name": str, "description": str, "input_schema": {...JSON Schema...}}

The Toolbox class holds callable implementations and is injected into the
runner so tests can substitute fakes without hitting real APIs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "get_features",
        "description": (
            "Return the latest technical-indicator snapshot for a single ticker: "
            "SMA-50/200, EMA-20, RSI-14, MACD, Bollinger Bands, ATR-14, ADX-14, "
            "volume ratio, and the current market regime "
            "(trending_up | trending_down | ranging | breakout | unknown)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_news",
        "description": (
            "Return recent news headlines and summaries for a ticker from Finnhub. "
            "Use this to check for earnings surprises, analyst upgrades/downgrades, "
            "product launches, or macro events that could move the price."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "limit": {
                    "type": "integer",
                    "description": "Max headlines to return (default 5, max 20)",
                    "default": 5,
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_portfolio",
        "description": (
            "Return current portfolio: cash balance, list of open positions "
            "(symbol, quantity, average cost, current price, unrealised P&L). "
            "Call this once at the start of your analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "propose_trade",
        "description": (
            "Record a trade proposal. Only call this when you have a clear signal "
            "with defined entry (limit_price) and risk (stop_price). "
            "Confidence must be 'high', 'medium', or 'low'. "
            "Provide a concise rationale (2-4 sentences) citing the specific signals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "quantity": {"type": "integer", "minimum": 1},
                "limit_price": {
                    "type": "number",
                    "description": "Limit order price in account currency",
                },
                "stop_price": {
                    "type": "number",
                    "description": "Stop-loss price (optional but strongly recommended)",
                },
                "rationale": {
                    "type": "string",
                    "description": "2-4 sentence explanation citing specific signals",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
            },
            "required": ["symbol", "side", "quantity", "limit_price", "rationale", "confidence"],
        },
    },
]


@dataclass
class Toolbox:
    """Container for tool implementations injected into the agent runner.

    Each attribute is a callable with signature ``(input_dict) -> Any``.
    The runner calls ``dispatch(name, inputs)`` which routes to the right fn.
    """

    get_features: Callable[[dict], Any]
    get_news: Callable[[dict], Any]
    get_portfolio: Callable[[dict], Any]
    propose_trade: Callable[[dict], Any]
    _proposals: list = field(default_factory=list)

    def dispatch(self, name: str, inputs: dict) -> Any:
        fn = {
            "get_features": self.get_features,
            "get_news": self.get_news,
            "get_portfolio": self.get_portfolio,
            "propose_trade": self._record_and_call(self.propose_trade),
        }.get(name)
        if fn is None:
            return {"error": f"unknown tool: {name!r}"}
        return fn(inputs)

    def _record_and_call(self, fn: Callable[[dict], Any]) -> Callable[[dict], Any]:
        def wrapper(inputs: dict) -> Any:
            result = fn(inputs)
            self._proposals.append(result)
            return result

        return wrapper
