from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from ai_agent.data import DataSourceError, RateLimitError, SymbolNotFoundError
from ai_agent.data.yahoo_chart_source import YahooChartSource


def _ts(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp())


CHART_OK = {
    "chart": {
        "result": [
            {
                "timestamp": [_ts(2026, 1, 2), _ts(2026, 1, 5)],
                "indicators": {
                    "quote": [
                        {
                            "open": [100.0, 101.5],
                            "high": [101.5, 103.0],
                            "low": [99.5, 100.8],
                            "close": [100.8, 102.4],
                            "volume": [12345678, 11223344],
                        }
                    ]
                },
            }
        ],
        "error": None,
    }
}

CHART_NOT_FOUND = {
    "chart": {
        "result": None,
        "error": {"code": "Not Found", "description": "No data found"},
    }
}

CHART_WITH_NULL_ROW = {
    "chart": {
        "result": [
            {
                "timestamp": [_ts(2026, 1, 2), _ts(2026, 1, 5)],
                "indicators": {
                    "quote": [
                        {
                            "open": [100.0, None],
                            "high": [101.5, None],
                            "low": [99.5, None],
                            "close": [100.8, None],
                            "volume": [12345678, None],
                        }
                    ]
                },
            }
        ],
        "error": None,
    }
}


def _client(body: object, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parses_chart_json() -> None:
    src = YahooChartSource(client=_client(CHART_OK))
    series = src.get_daily("AAPL", date(2026, 1, 1), date(2026, 1, 31))

    assert len(series) == 2
    assert series.symbol == "AAPL"
    assert series.points[0].trading_date == date(2026, 1, 2)
    assert series.points[0].open == Decimal("100.0")
    assert series.points[1].close == Decimal("102.4")
    assert series.source == "yahoo_chart"


def test_unknown_symbol_raises_symbol_not_found() -> None:
    src = YahooChartSource(client=_client(CHART_NOT_FOUND))
    with pytest.raises(SymbolNotFoundError):
        src.get_daily("ZZZZ", date(2026, 1, 1), date(2026, 1, 31))


def test_404_raises_symbol_not_found() -> None:
    src = YahooChartSource(client=_client("not found", status=404))
    with pytest.raises(SymbolNotFoundError):
        src.get_daily("ZZZZ", date(2026, 1, 1), date(2026, 1, 31))


def test_429_raises_rate_limit_error() -> None:
    src = YahooChartSource(client=_client("rate limited", status=429))
    with pytest.raises(RateLimitError):
        src.get_daily("AAPL", date(2026, 1, 1), date(2026, 1, 31))


def test_non_200_raises_data_source_error() -> None:
    src = YahooChartSource(client=_client("server error", status=503))
    with pytest.raises(DataSourceError):
        src.get_daily("AAPL", date(2026, 1, 1), date(2026, 1, 31))


def test_null_padded_rows_are_skipped() -> None:
    src = YahooChartSource(client=_client(CHART_WITH_NULL_ROW))
    series = src.get_daily("AAPL", date(2026, 1, 1), date(2026, 1, 31))

    assert len(series) == 1
    assert series.points[0].trading_date == date(2026, 1, 2)


def test_start_after_end_raises_value_error() -> None:
    src = YahooChartSource(client=_client(CHART_OK))
    with pytest.raises(ValueError):
        src.get_daily("AAPL", date(2026, 2, 1), date(2026, 1, 1))
