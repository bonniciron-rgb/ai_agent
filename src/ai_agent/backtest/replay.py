"""ReplayToolbox: feed pre-computed historical data into the agent during backtests.

The toolbox is re-built per bar so the agent only sees data up to that date
(no look-ahead).  News is optional; pass a news provider to include it.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pandas as pd

from ai_agent.agent.proposals import TradeProposal
from ai_agent.agent.tools import Toolbox
from ai_agent.db.models import OrderSide
from ai_agent.features import indicators as ind
from ai_agent.features.regime import classify_regime


def _compute_snapshot(df: pd.DataFrame) -> dict:
    """Return a plain dict of indicator values for the last row of *df*."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    def last(s: pd.Series) -> float | None:
        if s.empty:
            return None
        v = s.iloc[-1]
        return None if pd.isna(v) else float(v)

    sma_200 = ind.sma(close, 200)
    adx_14 = ind.adx(high, low, close, 14)
    _bb_mid, bb_upper, bb_lower = ind.bollinger_bands(close, 20, 2.0)

    regime = classify_regime(
        close=last(close),
        sma_200=last(sma_200),
        adx_14=last(adx_14),
        bb_upper=last(bb_upper),
        bb_lower=last(bb_lower),
    )

    return {
        "sma_50": last(ind.sma(close, 50)),
        "sma_200": last(sma_200),
        "ema_20": last(ind.ema(close, 20)),
        "rsi_14": last(ind.rsi(close, 14)),
        "adx_14": last(adx_14),
        "bb_upper": last(bb_upper),
        "bb_lower": last(bb_lower),
        "atr_14": last(ind.atr(high, low, close, 14)),
        "volume_ratio_20d": last(ind.volume_vs_avg(volume, 20)),
        "close": last(close),
        "regime": str(regime),
    }


def build_replay_toolbox(
    df_upto: pd.DataFrame,
    symbol: str,
    position: int,
    cash: float,
    news_fn: Callable[[str], list[dict]] | None = None,
) -> Toolbox:
    """Create a Toolbox that answers tool calls using data up to *df_upto*.

    Parameters
    ----------
    df_upto:
        OHLCV DataFrame sliced up to (and including) the current bar.
    symbol:
        Ticker being analysed.
    position:
        Current simulated share count.
    cash:
        Current simulated cash balance.
    news_fn:
        Optional callable ``(symbol) -> list[dict]`` for recent headlines.
        Defaults to returning an empty list.
    """
    snapshot = _compute_snapshot(df_upto)
    _news_fn = news_fn or (lambda _sym: [])

    def get_features(inputs: dict) -> dict:
        return {**snapshot, "symbol": inputs.get("symbol", symbol)}

    def get_news(inputs: dict) -> list[dict]:
        return _news_fn(inputs.get("symbol", symbol))

    def get_portfolio(_inputs: dict) -> dict:
        current_price = snapshot.get("close") or 0.0
        return {
            "cash": cash,
            "positions": (
                [
                    {
                        "symbol": symbol,
                        "quantity": position,
                        "current_price": current_price,
                        "unrealised_pnl": None,
                    }
                ]
                if position > 0
                else []
            ),
        }

    def propose_trade(inputs: dict) -> TradeProposal:
        return TradeProposal(
            symbol=inputs["symbol"],
            side=OrderSide(inputs["side"]),
            quantity=int(inputs["quantity"]),
            limit_price=Decimal(str(inputs["limit_price"])),
            stop_price=Decimal(str(inputs["stop_price"])) if inputs.get("stop_price") else None,
            rationale=inputs["rationale"],
            confidence=inputs["confidence"],
        )

    return Toolbox(
        get_features=get_features,
        get_news=get_news,
        get_portfolio=get_portfolio,
        propose_trade=propose_trade,
    )
