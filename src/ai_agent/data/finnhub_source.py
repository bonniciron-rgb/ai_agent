from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx
from pydantic import BaseModel

from ai_agent.data.base import DataSourceError, RateLimitError

FINNHUB_BASE = "https://finnhub.io/api/v1"


class EarningsEvent(BaseModel):
    symbol: str
    event_date: date
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None
    hour: str | None = None  # bmo (before market open) / amc (after market close)


class NewsItem(BaseModel):
    symbol: str
    headline: str
    summary: str = ""
    source: str = ""
    url: str = ""
    published_at: datetime
    category: str = ""


class FinnhubSource:
    """Finnhub free-tier adapter. 60 req/min limit.

    We use direct httpx rather than `finnhub-python` for testability and a
    smaller dependency surface.
    """

    name = "finnhub"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("FinnhubSource requires an api_key (FINNHUB_API_KEY)")
        self._api_key = api_key
        self._client = client
        self._timeout = timeout_seconds

    def _open(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self._timeout)

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        client = self._open()
        owns = self._client is None
        params = {**params, "token": self._api_key}
        try:
            resp = client.get(f"{FINNHUB_BASE}{path}", params=params)
        except httpx.HTTPError as e:
            raise DataSourceError(f"finnhub HTTP error: {e}") from e
        finally:
            if owns:
                client.close()

        if resp.status_code == 429:
            raise RateLimitError("finnhub rate limit hit")
        if resp.status_code != 200:
            raise DataSourceError(f"finnhub returned status {resp.status_code}: {resp.text[:200]}")

        try:
            return resp.json()
        except ValueError as e:
            raise DataSourceError(f"finnhub returned non-JSON: {e}") from e

    def earnings_calendar(self, symbol: str, *, start: date, end: date) -> list[EarningsEvent]:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")

        payload = self._get(
            "/calendar/earnings",
            {
                "symbol": symbol.upper(),
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )
        rows = payload.get("earningsCalendar") or []
        out: list[EarningsEvent] = []
        for row in rows:
            try:
                out.append(
                    EarningsEvent(
                        symbol=(row.get("symbol") or symbol).upper(),
                        event_date=date.fromisoformat(row["date"]),
                        eps_estimate=_maybe_float(row.get("epsEstimate")),
                        eps_actual=_maybe_float(row.get("epsActual")),
                        revenue_estimate=_maybe_float(row.get("revenueEstimate")),
                        revenue_actual=_maybe_float(row.get("revenueActual")),
                        hour=row.get("hour"),
                    )
                )
            except (KeyError, ValueError) as e:
                raise DataSourceError(f"finnhub earnings row malformed: {row}") from e
        return out

    def company_news(self, symbol: str, *, start: date, end: date) -> list[NewsItem]:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")

        payload = self._get(
            "/company-news",
            {
                "symbol": symbol.upper(),
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )
        rows: list[dict[str, Any]] = payload if isinstance(payload, list) else []
        out: list[NewsItem] = []
        for row in rows:
            try:
                ts = row.get("datetime")
                if ts is None:
                    continue
                published = datetime.fromtimestamp(int(ts), tz=UTC)
                out.append(
                    NewsItem(
                        symbol=symbol.upper(),
                        headline=row.get("headline", ""),
                        summary=row.get("summary", ""),
                        source=row.get("source", ""),
                        url=row.get("url", ""),
                        published_at=published,
                        category=row.get("category", ""),
                    )
                )
            except (KeyError, ValueError) as e:
                raise DataSourceError(f"finnhub news row malformed: {row}") from e
        return out


def _maybe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
