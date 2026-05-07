from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_agent.data import BarPoint, BarSeries


def _bar(day: int = 1) -> BarPoint:
    return BarPoint(
        symbol="aapl",
        trading_date=date(2026, 1, day),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=1_000_000,
        source="yfinance",
    )


def test_symbol_normalised_to_upper() -> None:
    bar = _bar()
    assert bar.symbol == "AAPL"


def test_negative_volume_rejected() -> None:
    with pytest.raises(ValidationError):
        BarPoint(
            symbol="AAPL",
            trading_date=date(2026, 1, 1),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=-1,
            source="yfinance",
        )


def test_bar_is_frozen() -> None:
    bar = _bar()
    with pytest.raises(ValidationError):
        bar.symbol = "MSFT"  # type: ignore[misc]


def test_series_iter_and_source() -> None:
    series = BarSeries(symbol="AAPL", points=[_bar(1), _bar(2)])
    assert len(series) == 2
    syms = [b.symbol for b in series]
    assert syms == ["AAPL", "AAPL"]
    assert series.source == "yfinance"


def test_empty_series_source_is_none() -> None:
    assert BarSeries(symbol="AAPL").source is None
