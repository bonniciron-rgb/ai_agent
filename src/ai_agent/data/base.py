from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator


class DataSourceError(Exception):
    """Base class for any failure inside a data source adapter."""


class RateLimitError(DataSourceError):
    """Provider rejected the request for rate-limit reasons."""


class SymbolNotFoundError(DataSourceError):
    """Provider has no data for the given symbol."""


class BarPoint(BaseModel):
    """A single OHLCV daily bar in transport form. DB persistence uses db.models.Bar."""

    model_config = {"frozen": True}

    symbol: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adj_close: Decimal | None = None
    volume: int = Field(ge=0)
    source: str

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class BarSeries(BaseModel):
    """An ordered sequence of bars for a single symbol."""

    symbol: str
    points: list[BarPoint] = Field(default_factory=list)

    def __len__(self) -> int:
        return len(self.points)

    def __iter__(self):  # type: ignore[override]
        return iter(self.points)

    @property
    def source(self) -> str | None:
        return self.points[0].source if self.points else None


@runtime_checkable
class OhlcvSource(Protocol):
    """Adapter contract for daily OHLCV providers.

    Implementations must be deterministic for the same (symbol, start, end)
    inputs over the lifetime of a single process — callers cache aggressively.
    """

    name: str

    def get_daily(self, symbol: str, start: date, end: date) -> BarSeries: ...
