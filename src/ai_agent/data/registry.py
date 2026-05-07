from __future__ import annotations

from datetime import date

from ai_agent.data.base import (
    BarSeries,
    DataSourceError,
    OhlcvSource,
    SymbolNotFoundError,
)
from ai_agent.logging import get_logger

log = get_logger(__name__)


class OhlcvChain:
    """Try a list of OHLCV sources in order; return the first success.

    If every source raises `DataSourceError`, the last error is re-raised.
    `SymbolNotFoundError` is treated like any other failure for fallback —
    the next source might know the symbol.
    """

    name = "chain"

    def __init__(self, sources: list[OhlcvSource]) -> None:
        if not sources:
            raise ValueError("OhlcvChain requires at least one source")
        self.sources = sources

    def get_daily(self, symbol: str, start: date, end: date) -> BarSeries:
        last_error: Exception | None = None
        for src in self.sources:
            try:
                return src.get_daily(symbol, start, end)
            except SymbolNotFoundError as e:
                log.info("source_no_data", source=src.name, symbol=symbol)
                last_error = e
            except DataSourceError as e:
                log.warning("source_failed", source=src.name, symbol=symbol, error=str(e))
                last_error = e

        assert last_error is not None
        raise last_error
