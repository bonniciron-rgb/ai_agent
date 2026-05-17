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

# Default no-ops so Toolbox stays backward-compatible for callers that don't
# wire every optional tool (e.g. backtest replay).
_noop_signals: Callable[[dict], Any] = lambda _: []  # noqa: E731
_noop_holdings: Callable[[dict], Any] = lambda _: {"institutional_holdings": []}  # noqa: E731

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
        "name": "get_external_signals",
        "description": (
            "Return recent trading signals scraped from external Telegram channels "
            "(e.g. Jdub Trades). Each signal includes ticker, direction, "
            "entry/stop/target prices, and conviction. "
            "Use as supplementary context alongside your own technical analysis — "
            "do not follow blindly. An empty list means no recent signals for that ticker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default 7)",
                    "default": 7,
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_institutional_holdings",
        "description": (
            "Return the latest disclosed equity holdings of widely-followed "
            "institutional investors (Berkshire Hathaway/Buffett, Scion/Burry, "
            "Pershing Square/Ackman) from their quarterly SEC 13F filings. "
            "Each manager's top holdings are listed with the percent of their "
            "portfolio. Treat this as 'smart money' conviction context — a "
            "stock being a large holding of a respected investor is supportive, "
            "but 13F data is up to 45 days stale, so never use it as a timing "
            "signal. Takes no arguments."
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

    ``get_external_signals`` defaults to a no-op so callers that don't need it
    (e.g. backtest replay) don't have to provide it.
    """

    get_features: Callable[[dict], Any]
    get_news: Callable[[dict], Any]
    get_portfolio: Callable[[dict], Any]
    propose_trade: Callable[[dict], Any]
    get_external_signals: Callable[[dict], Any] = field(default=_noop_signals)
    get_institutional_holdings: Callable[[dict], Any] = field(default=_noop_holdings)
    _proposals: list = field(default_factory=list)

    def dispatch(self, name: str, inputs: dict) -> Any:
        fn = {
            "get_features": self.get_features,
            "get_news": self.get_news,
            "get_portfolio": self.get_portfolio,
            "get_external_signals": self.get_external_signals,
            "get_institutional_holdings": self.get_institutional_holdings,
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
