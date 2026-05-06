from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ai_agent.data.base import (
    BarPoint,
    BarSeries,
    DataSourceError,
    SymbolNotFoundError,
)

if TYPE_CHECKING:
    import pandas as pd


class YFinanceSource:
    """yfinance OHLCV adapter. Free, unofficial — primary source.

    Yahoo's `download` API uses end-exclusive dates; we add one day so callers
    get the bar for `end` itself.
    """

    name = "yfinance"

    def __init__(self, *, auto_adjust: bool = False) -> None:
        self.auto_adjust = auto_adjust

    def _download(self, symbol: str, start: date, end: date) -> "pd.DataFrame":
        try:
            import yfinance as yf
        except ImportError as e:  # pragma: no cover
            raise DataSourceError(
                "yfinance is not installed. Install with extras: pip install '.[data]'"
            ) from e

        df = yf.download(
            symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=self.auto_adjust,
            progress=False,
            threads=False,
        )
        return df

    def get_daily(self, symbol: str, start: date, end: date) -> BarSeries:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")

        df = self._download(symbol, start, end)
        if df is None or df.empty:
            raise SymbolNotFoundError(f"yfinance returned no data for {symbol}")

        return _frame_to_series(symbol, df, source=self.name)


def _frame_to_series(symbol: str, df: Any, source: str) -> BarSeries:
    """Convert a yfinance DataFrame to a typed BarSeries.

    Handles both single-symbol (flat columns) and the MultiIndex columns
    yfinance uses when given a list of symbols.
    """
    points: list[BarPoint] = []
    cols = df.columns

    def _col(name: str) -> Any:
        try:
            if hasattr(cols, "nlevels") and cols.nlevels > 1:
                return df[(name, symbol.upper())] if (name, symbol.upper()) in cols else df[name]
            return df[name]
        except KeyError as e:
            raise DataSourceError(f"yfinance frame missing column {name!r}") from e

    opens = _col("Open")
    highs = _col("High")
    lows = _col("Low")
    closes = _col("Close")
    adj_closes = (
        _col("Adj Close")
        if ("Adj Close" in cols or _has_multilevel(cols, "Adj Close"))
        else None
    )
    volumes = _col("Volume")

    for ts, _ in df.iterrows():
        idx = ts
        try:
            trading_day = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        except (AttributeError, ValueError) as e:
            raise DataSourceError(f"unparseable yfinance index value: {idx!r}") from e

        try:
            o = Decimal(str(opens.loc[ts]))
            h = Decimal(str(highs.loc[ts]))
            low = Decimal(str(lows.loc[ts]))
            c = Decimal(str(closes.loc[ts]))
            v = int(volumes.loc[ts])
        except (KeyError, ValueError) as e:
            raise DataSourceError(f"yfinance row missing fields at {ts}") from e

        adj = Decimal(str(adj_closes.loc[ts])) if adj_closes is not None else None

        points.append(
            BarPoint(
                symbol=symbol,
                trading_date=trading_day,
                open=o,
                high=h,
                low=low,
                close=c,
                adj_close=adj,
                volume=v,
                source=source,
            )
        )

    return BarSeries(symbol=symbol.upper(), points=points)


def _has_multilevel(cols: Any, name: str) -> bool:
    if hasattr(cols, "nlevels") and cols.nlevels > 1:
        return any(name == lvl for lvl in cols.get_level_values(0))
    return False
