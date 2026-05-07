"""Trading 212 REST API client (V1 — equity only).

Supports both demo and live environments via ``base_url``.
All methods raise ``T212Error`` on non-2xx responses.

Usage
-----
client = T212Client(api_key="...", base_url="https://demo.trading212.com")
positions = client.get_positions()
order = client.place_limit_order("AAPL_US_EQ", quantity=Decimal("5"), limit_price=Decimal("175"))
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

from ai_agent.broker.models import (
    CashInfo,
    LimitOrderRequest,
    OpenPosition,
    OrderResponse,
    StopLimitOrderRequest,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, read=30.0)


class T212Error(Exception):
    """Raised when the Trading 212 API returns a non-2xx status."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"T212 API error {status_code}: {body[:200]}")


class T212RateLimitError(T212Error):
    """429 Too Many Requests."""


class T212Client:
    """Synchronous Trading 212 API client backed by httpx.

    Parameters
    ----------
    api_key:
        Trading 212 API key (demo or live).
    base_url:
        ``https://demo.trading212.com`` or ``https://live.trading212.com``.
    http_client:
        Optional pre-built httpx.Client for testing / connection pooling.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://demo.trading212.com",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": api_key, "Content-Type": "application/json"}
        self._http = http_client or httpx.Client(
            base_url=self._base_url,
            headers=self._headers,
            timeout=_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # Account / portfolio
    # ------------------------------------------------------------------

    def get_cash(self) -> CashInfo:
        """Return account cash balances."""
        data = self._get("/api/v0/equity/account/cash")
        return CashInfo.model_validate(data)

    def get_positions(self) -> list[OpenPosition]:
        """Return all open equity positions."""
        data = self._get("/api/v0/equity/portfolio/open-positions")
        return [OpenPosition.model_validate(p) for p in data]

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def get_orders(self) -> list[OrderResponse]:
        """List all active (non-filled, non-cancelled) orders."""
        data = self._get("/api/v0/equity/orders")
        return [OrderResponse.model_validate(o) for o in data]

    def place_limit_order(
        self,
        ticker: str,
        quantity: Decimal,
        limit_price: Decimal,
        time_validity: str = "GTC",
    ) -> OrderResponse:
        """Place a limit order.  *ticker* is the T212 instrument ticker, e.g. ``AAPL_US_EQ``."""
        req = LimitOrderRequest(
            ticker=ticker,
            quantity=quantity,
            limit_price=limit_price,
            time_validity=time_validity,
        )
        data = self._post(
            "/api/v0/equity/orders/limit",
            req.model_dump(by_alias=True, mode="json"),
        )
        return OrderResponse.model_validate(data)

    def place_stop_limit_order(
        self,
        ticker: str,
        quantity: Decimal,
        limit_price: Decimal,
        stop_price: Decimal,
        time_validity: str = "GTC",
    ) -> OrderResponse:
        """Place a stop-limit order."""
        req = StopLimitOrderRequest(
            ticker=ticker,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_validity=time_validity,
        )
        data = self._post(
            "/api/v0/equity/orders/stop-limit",
            req.model_dump(by_alias=True, mode="json"),
        )
        return OrderResponse.model_validate(data)

    def cancel_order(self, order_id: int) -> None:
        """Cancel an active order by its T212 order ID."""
        self._delete(f"/api/v0/equity/orders/{order_id}")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Any:
        response = self._http.get(path)
        self._raise_for_status(response)
        return response.json()

    def _post(self, path: str, body: dict) -> Any:
        response = self._http.post(path, json=body)
        self._raise_for_status(response)
        return response.json()

    def _delete(self, path: str) -> None:
        response = self._http.delete(path)
        self._raise_for_status(response)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        body = response.text
        if response.status_code == 429:
            raise T212RateLimitError(response.status_code, body)
        raise T212Error(response.status_code, body)
