from datetime import date
from decimal import Decimal

import httpx
import pytest

from ai_agent.data import DataSourceError, SymbolNotFoundError
from ai_agent.data.stooq_source import StooqSource

CSV_BODY = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-01-02,100.00,101.50,99.50,100.80,12345678\n"
    "2026-01-03,100.80,102.10,100.20,101.90,11223344\n"
)


def _client_returning(body: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parses_csv_successfully() -> None:
    src = StooqSource(client=_client_returning(CSV_BODY))
    series = src.get_daily("AAPL", date(2026, 1, 1), date(2026, 1, 31))

    assert len(series) == 2
    assert series.symbol == "AAPL"
    assert series.points[0].trading_date == date(2026, 1, 2)
    assert series.points[0].open == Decimal("100.00")
    assert series.points[1].close == Decimal("101.90")
    assert series.source == "stooq"


def test_no_data_raises_symbol_not_found() -> None:
    src = StooqSource(client=_client_returning("No data\n"))
    with pytest.raises(SymbolNotFoundError):
        src.get_daily("ZZZZ", date(2026, 1, 1), date(2026, 1, 31))


def test_empty_response_raises_symbol_not_found() -> None:
    src = StooqSource(client=_client_returning(""))
    with pytest.raises(SymbolNotFoundError):
        src.get_daily("ZZZZ", date(2026, 1, 1), date(2026, 1, 31))


def test_non_200_status_raises_data_source_error() -> None:
    src = StooqSource(client=_client_returning("server error", status=503))
    with pytest.raises(DataSourceError):
        src.get_daily("AAPL", date(2026, 1, 1), date(2026, 1, 31))


def test_start_after_end_raises_value_error() -> None:
    src = StooqSource(client=_client_returning(CSV_BODY))
    with pytest.raises(ValueError):
        src.get_daily("AAPL", date(2026, 2, 1), date(2026, 1, 1))


def test_stooq_symbol_uses_us_suffix_for_plain_tickers() -> None:
    assert StooqSource._stooq_symbol("AAPL") == "aapl.us"
    assert StooqSource._stooq_symbol("brk.b") == "brk.b"
