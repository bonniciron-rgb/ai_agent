"""Tests for TOOL_SCHEMAS structure and Toolbox dispatch."""

from ai_agent.agent.tools import TOOL_SCHEMAS, Toolbox


def test_tool_schemas_have_required_keys() -> None:
    for schema in TOOL_SCHEMAS:
        assert "name" in schema
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"
        assert "required" in schema["input_schema"]


def test_all_expected_tools_present() -> None:
    names = {s["name"] for s in TOOL_SCHEMAS}
    assert names == {
        "get_features",
        "get_news",
        "get_portfolio",
        "get_external_signals",
        "get_institutional_holdings",
        "propose_trade",
    }


def test_toolbox_dispatch_get_features() -> None:
    calls = []

    def fake_get_features(inputs):
        calls.append(inputs)
        return {"regime": "trending_up", "rsi_14": 55.0}

    box = Toolbox(
        get_features=fake_get_features,
        get_news=lambda i: [],
        get_portfolio=lambda i: {"cash": 10000},
        propose_trade=lambda i: i,
    )
    result = box.dispatch("get_features", {"symbol": "AAPL"})
    assert result["regime"] == "trending_up"
    assert calls == [{"symbol": "AAPL"}]


def test_toolbox_dispatch_unknown_tool_returns_error() -> None:
    box = Toolbox(
        get_features=lambda i: {},
        get_news=lambda i: [],
        get_portfolio=lambda i: {},
        propose_trade=lambda i: i,
    )
    result = box.dispatch("nonexistent_tool", {})
    assert "error" in result


def test_toolbox_get_external_signals_default_noop() -> None:
    box = Toolbox(
        get_features=lambda i: {},
        get_news=lambda i: [],
        get_portfolio=lambda i: {},
        propose_trade=lambda i: i,
    )
    result = box.dispatch("get_external_signals", {"symbol": "AAPL"})
    assert result == []


def test_toolbox_get_external_signals_injected() -> None:
    def fake_signals(inputs):
        return [{"symbol": inputs["symbol"], "side": "buy"}]

    box = Toolbox(
        get_features=lambda i: {},
        get_news=lambda i: [],
        get_portfolio=lambda i: {},
        propose_trade=lambda i: i,
        get_external_signals=fake_signals,
    )
    result = box.dispatch("get_external_signals", {"symbol": "AAPL"})
    assert result == [{"symbol": "AAPL", "side": "buy"}]


def test_toolbox_propose_trade_recorded() -> None:
    from decimal import Decimal

    from ai_agent.agent.proposals import TradeProposal
    from ai_agent.db.models import OrderSide

    def fake_propose(inputs):
        return TradeProposal(
            symbol=inputs["symbol"],
            side=OrderSide(inputs["side"]),
            quantity=inputs["quantity"],
            limit_price=Decimal(str(inputs["limit_price"])),
            rationale=inputs["rationale"],
            confidence=inputs["confidence"],
        )

    box = Toolbox(
        get_features=lambda i: {},
        get_news=lambda i: [],
        get_portfolio=lambda i: {},
        propose_trade=fake_propose,
    )
    box.dispatch(
        "propose_trade",
        {
            "symbol": "MSFT",
            "side": "buy",
            "quantity": 5,
            "limit_price": 300.0,
            "rationale": "Strong trend.",
            "confidence": "medium",
        },
    )
    assert len(box._proposals) == 1
    assert box._proposals[0].symbol == "MSFT"
