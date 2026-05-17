"""Backup OHLCV source via Yahoo's public chart API.

The primary source (``YFinanceSource``) uses the *yfinance* library, which
breaks frequently when Yahoo changes its private endpoints. This adapter
calls the stable ``/v8/finance/chart`` JSON endpoint directly and does its
own parsing, so a library-level break does not take both sources down.
Keyless — no API key required.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ai_agent.data.base import (
    BarPoint,
    BarSeries,
    DataSourceError,
    RateLimitError,
    SymbolNotFoundError,
)

CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/"

# Yahoo rejects requests that look automated / have no User-Agent.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-agent/1.0)"}


class YahooChartSource:
    """Daily OHLCV adapter for Yahoo's ``/v8/finance/chart`` endpoint."""

    name = "yahoo_chart"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._client = client
        self._timeout = timeout_seconds

    def _open(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self._timeout)

    def get_daily(self, symbol: str, start: date, end: date) -> BarSeries:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")

        params = {
            "interval": "1d",
            "period1": _to_unix(start),
            # Yahoo's period2 is exclusive; add a day to include `end` itself.
            "period2": _to_unix(end + timedelta(days=1)),
        }

        client = self._open()
        owns_client = self._client is None
        try:
            resp = client.get(
                f"{CHART_URL}{symbol.strip().upper()}",
                params=params,
                headers=_HEADERS,
            )
        except httpx.HTTPError as e:
            raise DataSourceError(f"yahoo chart HTTP error: {e}") from e
        finally:
            if owns_client:
                client.close()

        if resp.status_code == 429:
            raise RateLimitError("yahoo chart rate-limited (429)")
        if resp.status_code == 404:
            raise SymbolNotFoundError(f"yahoo chart has no data for {symbol}")
        if resp.status_code != 200:
            raise DataSourceError(f"yahoo chart returned status {resp.status_code}")

        try:
            body = resp.json()
        except ValueError as e:
            raise DataSourceError("yahoo chart returned a non-JSON body") from e

        return _chart_to_series(symbol, body, source=self.name)


def _to_unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def _at(seq: list[Any], i: int) -> Any:
    return seq[i] if i < len(seq) else None


def _chart_to_series(symbol: str, body: dict[str, Any], source: str) -> BarSeries:
    chart = body.get("chart") or {}
    if chart.get("error"):
        raise SymbolNotFoundError(f"yahoo chart error for {symbol}: {chart['error']}")

    results = chart.get("result")
    if not results:
        raise SymbolNotFoundError(f"yahoo chart returned no result for {symbol}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    points: list[BarPoint] = []
    for i, ts in enumerate(timestamps):
        o, h, low, c = _at(opens, i), _at(highs, i), _at(lows, i), _at(closes, i)
        if o is None or h is None or low is None or c is None:
            continue  # Yahoo pads gaps (e.g. holidays) with nulls
        try:
            point = BarPoint(
                symbol=symbol,
                trading_date=datetime.fromtimestamp(ts, tz=UTC).date(),
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(low)),
                close=Decimal(str(c)),
                volume=int(_at(volumes, i) or 0),
                source=source,
            )
        except (ValueError, TypeError, InvalidOperation) as e:
            raise DataSourceError(f"yahoo chart malformed row for {symbol}") from e
        points.append(point)

    if not points:
        raise SymbolNotFoundError(f"yahoo chart returned 0 usable rows for {symbol}")

    return BarSeries(symbol=symbol.upper(), points=points)
