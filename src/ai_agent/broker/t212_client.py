"""Trading 212 REST API client (V1 — equity only).

Supports both demo and live environments via ``base_url``.
All methods raise ``T212Error`` on non-2xx responses.

Authentication
--------------
The Trading 212 API uses HTTP Basic auth: the API *key* is the username and
the API *secret* is the password. The ``Authorization`` header is
``Basic <base64(api_key:api_secret)>``. Both halves are required — a raw key
alone returns 401.

Usage
-----
client = T212Client(api_key="...", api_secret="...", base_url="https://demo.trading212.com")
positions = client.get_positions()
order = client.place_limit_order("AAPL_US_EQ", quantity=Decimal("5"), limit_price=Decimal("175"))
"""

from __future__ import annotations

import base64
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
        Trading 212 API key (the "username" half of the Basic-auth pair).
    api_secret:
        Trading 212 API secret (the "password" half). Required for live calls;
        defaults to "" only so test code with a mock transport can omit it.
    base_url:
        ``https://demo.trading212.com`` or ``https://live.trading212.com``.
    http_client:
        Optional pre-built httpx.Client for testing / connection pooling.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str = "",
        base_url: str = "https://demo.trading212.com",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # HTTP Basic auth — base64(api_key:api_secret). .strip() guards against a
        # stray newline/space pasted into an env var (a common 401 cause).
        raw = f"{api_key.strip()}:{api_secret.strip()}"
        token = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        self._headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
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
        data = self._get("/api/v0/equity/portfolio")
        return [OpenPosition.model_validate(p) for p in data]

    def get_instruments(self) -> dict[str, str]:
        """Return ``{ticker: currencyCode}`` for the T212 instrument universe.

        Used to convert position prices (quoted in the instrument's own
        currency — USD, GBX, …) into the GBP account currency.
        """
        data = self._get("/api/v0/equity/metadata/instruments")
        out: dict[str, str] = {}
        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                ticker = it.get("ticker")
                currency = it.get("currencyCode")
                if isinstance(ticker, str) and isinstance(currency, str):
                    out[ticker] = currency
        return out

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
