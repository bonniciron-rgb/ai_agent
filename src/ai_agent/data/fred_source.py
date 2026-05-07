from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import BaseModel

from ai_agent.data.base import DataSourceError, RateLimitError, SymbolNotFoundError

FRED_BASE = "https://api.stlouisfed.org/fred"


class MacroPoint(BaseModel):
    series_id: str
    observation_date: date
    value: Decimal | None  # FRED uses "." for missing values


class FredSource:
    """St. Louis Fed FRED adapter for macro time series.

    Free, requires API key (`FRED_API_KEY`). Common series for V1:
      - DGS10        : 10-year treasury yield
      - T10Y2Y       : 10y-2y spread (recession indicator)
      - CPIAUCSL     : CPI all urban consumers
      - UNRATE       : unemployment rate
      - VIXCLS       : VIX close
    """

    name = "fred"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("FredSource requires an api_key (FRED_API_KEY)")
        self._api_key = api_key
        self._client = client
        self._timeout = timeout_seconds

    def _open(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self._timeout)

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        params = {**params, "api_key": self._api_key, "file_type": "json"}
        client = self._open()
        owns = self._client is None
        try:
            resp = client.get(f"{FRED_BASE}{path}", params=params)
        except httpx.HTTPError as e:
            raise DataSourceError(f"fred HTTP error: {e}") from e
        finally:
            if owns:
                client.close()

        if resp.status_code == 429:
            raise RateLimitError("fred rate limit hit")
        if resp.status_code == 400 and "series does not exist" in resp.text:
            raise SymbolNotFoundError(f"fred has no series for {params.get('series_id')}")
        if resp.status_code != 200:
            raise DataSourceError(f"fred returned status {resp.status_code}: {resp.text[:200]}")

        try:
            return resp.json()
        except ValueError as e:
            raise DataSourceError(f"fred returned non-JSON: {e}") from e

    def series(
        self,
        series_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> list[MacroPoint]:
        params: dict[str, Any] = {"series_id": series_id}
        if start:
            params["observation_start"] = start.isoformat()
        if end:
            params["observation_end"] = end.isoformat()

        payload = self._get("/series/observations", params)
        observations = payload.get("observations") or []

        out: list[MacroPoint] = []
        for row in observations:
            try:
                obs_date = date.fromisoformat(row["date"])
            except (KeyError, ValueError) as e:
                raise DataSourceError(f"fred row malformed: {row}") from e

            raw = row.get("value")
            value: Decimal | None
            if raw in (None, "", "."):
                value = None
            else:
                try:
                    value = Decimal(str(raw))
                except InvalidOperation:
                    value = None

            out.append(MacroPoint(series_id=series_id, observation_date=obs_date, value=value))
        return out
