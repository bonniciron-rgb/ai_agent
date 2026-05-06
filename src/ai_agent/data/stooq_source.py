from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from ai_agent.data.base import (
    BarPoint,
    BarSeries,
    DataSourceError,
    SymbolNotFoundError,
)

STOOQ_URL = "https://stooq.com/q/d/l/"


class StooqSource:
    """Backup OHLCV source via Stooq's public CSV endpoint.

    Used when yfinance is unavailable (Yahoo occasionally breaks the unofficial
    API). Stooq covers US tickers as `<ticker>.us`.
    """

    name = "stooq"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._timeout = timeout_seconds

    def _open(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self._timeout)

    @staticmethod
    def _stooq_symbol(symbol: str) -> str:
        s = symbol.strip().upper()
        return s.lower() + ".us" if "." not in s else s.lower()

    def get_daily(self, symbol: str, start: date, end: date) -> BarSeries:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")

        params = {
            "s": self._stooq_symbol(symbol),
            "i": "d",
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
        }

        client = self._open()
        owns_client = self._client is None
        try:
            resp = client.get(STOOQ_URL, params=params)
        except httpx.HTTPError as e:
            raise DataSourceError(f"stooq HTTP error: {e}") from e
        finally:
            if owns_client:
                client.close()

        if resp.status_code != 200:
            raise DataSourceError(f"stooq returned status {resp.status_code}")

        text = resp.text.strip()
        if not text or text.lower().startswith("no data"):
            raise SymbolNotFoundError(f"stooq has no data for {symbol}")

        return _csv_to_series(symbol, text, source=self.name)


def _csv_to_series(symbol: str, text: str, source: str) -> BarSeries:
    reader = csv.DictReader(io.StringIO(text))
    points: list[BarPoint] = []

    for row in reader:
        try:
            trading_day = date.fromisoformat(row["Date"])
            o = Decimal(row["Open"])
            h = Decimal(row["High"])
            low = Decimal(row["Low"])
            c = Decimal(row["Close"])
            v = int(row.get("Volume") or 0)
        except (KeyError, ValueError, InvalidOperation) as e:
            raise DataSourceError(f"stooq malformed row {row}") from e

        points.append(
            BarPoint(
                symbol=symbol,
                trading_date=trading_day,
                open=o,
                high=h,
                low=low,
                close=c,
                volume=v,
                source=source,
            )
        )

    if not points:
        raise SymbolNotFoundError(f"stooq returned 0 rows for {symbol}")

    return BarSeries(symbol=symbol.upper(), points=points)
