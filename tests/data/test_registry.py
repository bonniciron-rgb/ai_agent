from datetime import date
from decimal import Decimal

import pytest

from ai_agent.data import (
    BarPoint,
    BarSeries,
    DataSourceError,
    OhlcvChain,
    SymbolNotFoundError,
)


class _Source:
    def __init__(self, name: str, behaviour) -> None:
        self.name = name
        self._behaviour = behaviour
        self.calls = 0

    def get_daily(self, symbol: str, start: date, end: date) -> BarSeries:
        self.calls += 1
        return self._behaviour(symbol, start, end)


def _good(symbol: str, start: date, end: date) -> BarSeries:
    return BarSeries(
        symbol=symbol,
        points=[
            BarPoint(
                symbol=symbol,
                trading_date=start,
                open=Decimal("1"),
                high=Decimal("1"),
                low=Decimal("1"),
                close=Decimal("1"),
                volume=1,
                source="ok",
            )
        ],
    )


def _raise(exc: Exception):
    def _f(symbol: str, start: date, end: date) -> BarSeries:
        raise exc

    return _f


def test_returns_first_success() -> None:
    primary = _Source("primary", _good)
    backup = _Source("backup", _raise(DataSourceError("never called")))
    chain = OhlcvChain([primary, backup])

    series = chain.get_daily("AAPL", date(2026, 1, 2), date(2026, 1, 3))

    assert series.symbol == "AAPL"
    assert primary.calls == 1
    assert backup.calls == 0


def test_falls_back_on_data_source_error() -> None:
    primary = _Source("primary", _raise(DataSourceError("yahoo down")))
    backup = _Source("backup", _good)
    chain = OhlcvChain([primary, backup])

    series = chain.get_daily("AAPL", date(2026, 1, 2), date(2026, 1, 3))

    assert series.points[0].source == "ok"
    assert primary.calls == 1
    assert backup.calls == 1


def test_falls_back_on_symbol_not_found() -> None:
    primary = _Source("primary", _raise(SymbolNotFoundError("not on yahoo")))
    backup = _Source("backup", _good)
    chain = OhlcvChain([primary, backup])

    series = chain.get_daily("AAPL", date(2026, 1, 2), date(2026, 1, 3))

    assert primary.calls == 1
    assert backup.calls == 1
    assert len(series) == 1


def test_all_failures_reraises_last() -> None:
    primary = _Source("primary", _raise(DataSourceError("a")))
    backup = _Source("backup", _raise(SymbolNotFoundError("b")))
    chain = OhlcvChain([primary, backup])

    with pytest.raises(SymbolNotFoundError):
        chain.get_daily("XXXX", date(2026, 1, 2), date(2026, 1, 3))


def test_empty_sources_rejected() -> None:
    with pytest.raises(ValueError):
        OhlcvChain([])
