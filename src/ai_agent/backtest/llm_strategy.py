"""LlmStrategy: plugs run_agent into the bar-by-bar backtest engine.

The agent is called once per bar (or every N bars when call_every is set).
Each call gets a ReplayToolbox sliced up to the current bar so the agent
never sees future prices.

Cost note: calling the LLM for every bar of a 3-year backtest x 30 tickers
is expensive (~2700 API calls).  Use call_every=5 (weekly) or call_every=21
(monthly) for economics.  Tests always use a ScriptedClient.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from ai_agent.agent.runner import AgentResult, run_agent
from ai_agent.backtest.replay import build_replay_toolbox
from ai_agent.db.models import OrderSide


class LlmStrategy:
    """Strategy that invokes the Claude agent to decide each trade.

    Parameters
    ----------
    df:
        Full OHLCV history for the symbol being tested.
    symbol:
        Ticker label.
    client:
        Anthropic client or ScriptedClient fake.  If None the real SDK is used.
    call_every:
        Only call the agent every N bars (default 1 = daily).  On silent bars
        the last signal is NOT repeated — the agent must re-propose on each
        active bar.
    news_fn:
        Optional ``(symbol) -> list[dict]`` for replay news headlines.
    shares_per_trade:
        Fixed lot size when the agent omits quantity.  Falls back to the
        proposed quantity from the agent.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        symbol: str,
        client: Any = None,
        *,
        call_every: int = 1,
        news_fn: Callable[[str], list[dict]] | None = None,
        shares_per_trade: int | None = None,
    ) -> None:
        self._df = df.sort_index()
        self._symbol = symbol
        self._client = client
        self._call_every = max(1, call_every)
        self._news_fn = news_fn
        self._shares_per_trade = shares_per_trade
        self._bar_counter = 0
        self._last_result: AgentResult | None = None

    def reset(self) -> None:
        self._bar_counter = 0
        self._last_result = None

    def on_bar(
        self,
        *,
        date: pd.Timestamp,
        row: pd.Series,
        position: int,
        cash: float,
    ) -> int:
        self._bar_counter += 1

        if self._bar_counter % self._call_every != 0:
            return 0

        # Slice history up to this bar (inclusive) — no look-ahead
        df_upto = self._df.loc[: str(date)]
        if df_upto.empty:
            return 0

        toolbox = build_replay_toolbox(
            df_upto,
            self._symbol,
            position,
            cash,
            news_fn=self._news_fn,
        )

        result = run_agent(
            watchlist=[self._symbol],
            toolbox=toolbox,
            client=self._client,
            tiered=False,  # single-symbol backtest; screening adds no value
        )
        self._last_result = result

        if not result.proposals:
            return 0

        proposal = result.proposals[0]
        qty = self._shares_per_trade if self._shares_per_trade is not None else proposal.quantity

        if proposal.side == OrderSide.buy and position == 0:
            return qty
        if proposal.side == OrderSide.sell and position > 0:
            return -min(qty, position)

        return 0
