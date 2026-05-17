"""Tests for T212Client using httpx mock transport (no real network calls)."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from ai_agent.broker.t212_client import T212Client, T212Error, T212RateLimitError

# ---------------------------------------------------------------------------
# Mock transport helpers
# ---------------------------------------------------------------------------


def _mock_client(responses: dict[str, tuple[int, object]]) -> httpx.Client:
    """Build an httpx.Client backed by a mock transport.

    *responses* maps URL paths to ``(status_code, body)`` tuples.
    ``body`` can be a dict/list (serialised to JSON) or a string.
    """

    class _Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path not in responses:
                return httpx.Response(404, text=f"Not found: {path}")
            status, body = responses[path]
            content = json.dumps(body) if not isinstance(body, str) else body
            return httpx.Response(
                status, text=content, headers={"content-type": "application/json"}
            )

    return httpx.Client(transport=_Transport(), base_url="https://demo.trading212.com")


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

CASH_PAYLOAD = {
    "free": "9500.00",
    "total": "10000.00",
    "ppl": "500.00",
    "result": "0.00",
    "invested": "500.00",
    "pieCash": "0.00",
}

POSITIONS_PAYLOAD = [
    {
        "ticker": "AAPL_US_EQ",
        "quantity": "5",
        "averagePrice": "170.00",
        "currentPrice": "175.00",
        "ppl": "25.00",
        "fxPpl": "0.00",
        "initialFillDate": "2024-01-10T10:00:00Z",
        "frontend": "WC4",
    }
]

ORDER_RESPONSE_PAYLOAD = {
    "id": 12345,
    "ticker": "AAPL_US_EQ",
    "quantity": "5",
    "status": "CONFIRMED",
    "type": "LIMIT",
    "limitPrice": "175.00",
    "stopPrice": None,
    "filledQuantity": "0",
    "fillPrice": None,
    "timeValidity": "GTC",
    "creationTime": "2024-01-10T10:00:00Z",
}


# ---------------------------------------------------------------------------
# Tests: get_cash
# ---------------------------------------------------------------------------


def test_get_cash_parses_response() -> None:
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/account/cash": (200, CASH_PAYLOAD)}),
    )
    cash = client.get_cash()
    assert cash.free == Decimal("9500.00")
    assert cash.total == Decimal("10000.00")
    assert cash.ppl == Decimal("500.00")


# ---------------------------------------------------------------------------
# Tests: get_positions
# ---------------------------------------------------------------------------


def test_get_positions_returns_list() -> None:
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/portfolio": (200, POSITIONS_PAYLOAD)}),
    )
    positions = client.get_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert pos.ticker == "AAPL_US_EQ"
    assert pos.quantity == Decimal("5")
    assert pos.average_price == Decimal("170.00")


def test_get_positions_empty_list() -> None:
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/portfolio": (200, [])}),
    )
    assert client.get_positions() == []


def test_get_positions_handles_null_fx_ppl() -> None:
    """T212 sends fxPpl=null for account-currency instruments (e.g. London ETFs)."""
    payload = [{**POSITIONS_PAYLOAD[0], "fxPpl": None, "ppl": None}]
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/portfolio": (200, payload)}),
    )
    positions = client.get_positions()
    assert len(positions) == 1
    assert positions[0].fx_ppl == Decimal("0")
    assert positions[0].ppl == Decimal("0")


# ---------------------------------------------------------------------------
# Tests: get_orders
# ---------------------------------------------------------------------------


def test_get_orders_returns_list() -> None:
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/orders": (200, [ORDER_RESPONSE_PAYLOAD])}),
    )
    orders = client.get_orders()
    assert len(orders) == 1
    assert orders[0].id == 12345
    assert orders[0].status == "CONFIRMED"


# ---------------------------------------------------------------------------
# Tests: place_limit_order
# ---------------------------------------------------------------------------


def test_place_limit_order_returns_order() -> None:
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/orders/limit": (200, ORDER_RESPONSE_PAYLOAD)}),
    )
    order = client.place_limit_order(
        ticker="AAPL_US_EQ",
        quantity=Decimal("5"),
        limit_price=Decimal("175.00"),
    )
    assert order.id == 12345
    assert order.ticker == "AAPL_US_EQ"
    assert order.limit_price == Decimal("175.00")


# ---------------------------------------------------------------------------
# Tests: place_stop_limit_order
# ---------------------------------------------------------------------------


def test_place_stop_limit_order_returns_order() -> None:
    stop_limit_payload = {**ORDER_RESPONSE_PAYLOAD, "type": "STOP_LIMIT", "stopPrice": "168.00"}
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/orders/stop-limit": (200, stop_limit_payload)}),
    )
    order = client.place_stop_limit_order(
        ticker="AAPL_US_EQ",
        quantity=Decimal("5"),
        limit_price=Decimal("175.00"),
        stop_price=Decimal("168.00"),
    )
    assert order.type == "STOP_LIMIT"
    assert order.stop_price == Decimal("168.00")


# ---------------------------------------------------------------------------
# Tests: cancel_order
# ---------------------------------------------------------------------------


def test_cancel_order_succeeds_on_200() -> None:
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/orders/12345": (200, "")}),
    )
    client.cancel_order(12345)  # should not raise


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


def test_raises_t212_error_on_400() -> None:
    client = T212Client(
        api_key="test",
        http_client=_mock_client(
            {"/api/v0/equity/account/cash": (400, {"code": "InvalidRequest"})}
        ),
    )
    with pytest.raises(T212Error) as exc_info:
        client.get_cash()
    assert exc_info.value.status_code == 400


def test_raises_rate_limit_error_on_429() -> None:
    client = T212Client(
        api_key="test",
        http_client=_mock_client({"/api/v0/equity/account/cash": (429, "Too many requests")}),
    )
    with pytest.raises(T212RateLimitError):
        client.get_cash()


def test_raises_t212_error_on_401() -> None:
    client = T212Client(
        api_key="bad-key",
        http_client=_mock_client({"/api/v0/equity/account/cash": (401, "Unauthorized")}),
    )
    with pytest.raises(T212Error) as exc_info:
        client.get_cash()
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests: HTTP Basic authentication header
# ---------------------------------------------------------------------------


def test_basic_auth_header_built_from_key_and_secret() -> None:
    import base64

    client = T212Client(api_key="mykey", api_secret="mysecret")
    expected = "Basic " + base64.b64encode(b"mykey:mysecret").decode()
    assert client._headers["Authorization"] == expected


def test_basic_auth_strips_whitespace_from_credentials() -> None:
    import base64

    # A stray newline/space pasted into an env var must not break the header.
    client = T212Client(api_key="  mykey\n", api_secret=" mysecret ")
    expected = "Basic " + base64.b64encode(b"mykey:mysecret").decode()
    assert client._headers["Authorization"] == expected
