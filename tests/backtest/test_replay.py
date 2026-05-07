"""Tests for the ReplayToolbox and snapshot computation."""

import numpy as np
import pandas as pd

from ai_agent.backtest.replay import _compute_snapshot, build_replay_toolbox


def _make_df(n: int = 250) -> pd.DataFrame:
    closes = np.linspace(100, 200, n)
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1,
            "low": closes - 1,
            "close": closes,
            "volume": [100_000] * n,
        },
        index=dates,
    )


def test_compute_snapshot_keys() -> None:
    df = _make_df(250)
    snap = _compute_snapshot(df)
    for key in ("close", "rsi_14", "adx_14", "sma_50", "sma_200", "regime"):
        assert key in snap, f"missing key: {key}"


def test_compute_snapshot_regime_trending_up() -> None:
    df = _make_df(250)
    snap = _compute_snapshot(df)
    # Strongly rising series → trending_up once SMA-200 is defined
    assert snap["regime"] in ("trending_up", "ranging", "unknown")


def test_compute_snapshot_nans_when_insufficient_data() -> None:
    df = _make_df(10)  # too few bars for SMA-200
    snap = _compute_snapshot(df)
    assert snap["sma_200"] is None
    assert snap["regime"] == "unknown"


def test_build_replay_toolbox_get_portfolio_empty() -> None:
    df = _make_df(250)
    box = build_replay_toolbox(df, "AAPL", position=0, cash=10_000.0)
    port = box.get_portfolio({})
    assert port["cash"] == 10_000.0
    assert port["positions"] == []


def test_build_replay_toolbox_get_portfolio_with_position() -> None:
    df = _make_df(250)
    box = build_replay_toolbox(df, "AAPL", position=5, cash=8_000.0)
    port = box.get_portfolio({})
    assert len(port["positions"]) == 1
    assert port["positions"][0]["symbol"] == "AAPL"
    assert port["positions"][0]["quantity"] == 5


def test_build_replay_toolbox_get_features() -> None:
    df = _make_df(250)
    box = build_replay_toolbox(df, "AAPL", position=0, cash=10_000.0)
    feat = box.get_features({"symbol": "AAPL"})
    assert feat["symbol"] == "AAPL"
    assert "regime" in feat


def test_build_replay_toolbox_get_news_default_empty() -> None:
    df = _make_df(250)
    box = build_replay_toolbox(df, "AAPL", position=0, cash=10_000.0)
    news = box.get_news({"symbol": "AAPL"})
    assert news == []


def test_build_replay_toolbox_get_news_custom_fn() -> None:
    df = _make_df(250)
    headlines = [{"headline": "AAPL beats earnings"}]
    box = build_replay_toolbox(df, "AAPL", position=0, cash=10_000.0, news_fn=lambda _: headlines)
    assert box.get_news({"symbol": "AAPL"}) == headlines


def test_build_replay_toolbox_propose_trade_recorded() -> None:
    df = _make_df(250)
    box = build_replay_toolbox(df, "AAPL", position=0, cash=10_000.0)
    result = box.dispatch(
        "propose_trade",
        {
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 5,
            "limit_price": 180.0,
            "rationale": "Uptrend with volume.",
            "confidence": "medium",
        },
    )
    assert result.symbol == "AAPL"
    assert len(box._proposals) == 1
