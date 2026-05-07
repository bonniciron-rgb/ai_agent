from datetime import UTC, date, datetime

import httpx
import pytest

from ai_agent.data import DataSourceError, RateLimitError
from ai_agent.data.finnhub_source import FinnhubSource


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_requires_api_key() -> None:
    with pytest.raises(ValueError):
        FinnhubSource("")


def test_earnings_calendar_parses_payload() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "earningsCalendar": [
                    {
                        "symbol": "AAPL",
                        "date": "2026-02-01",
                        "epsEstimate": 2.10,
                        "epsActual": 2.18,
                        "revenueEstimate": 1.2e11,
                        "revenueActual": 1.23e11,
                        "hour": "amc",
                    }
                ]
            },
        )

    src = FinnhubSource("k", client=_client(handler))
    out = src.earnings_calendar("aapl", start=date(2026, 1, 1), end=date(2026, 3, 1))

    assert "token=k" in captured["url"]
    assert len(out) == 1
    assert out[0].symbol == "AAPL"
    assert out[0].event_date == date(2026, 2, 1)
    assert out[0].eps_actual == 2.18
    assert out[0].hour == "amc"


def test_earnings_calendar_handles_missing_estimates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "earningsCalendar": [
                    {"symbol": "MSFT", "date": "2026-02-01", "epsEstimate": None, "epsActual": ""},
                ]
            },
        )

    src = FinnhubSource("k", client=_client(handler))
    out = src.earnings_calendar("MSFT", start=date(2026, 1, 1), end=date(2026, 3, 1))
    assert out[0].eps_estimate is None
    assert out[0].eps_actual is None


def test_company_news_parses_payload() -> None:
    ts = int(datetime(2026, 5, 1, 12, 0, tzinfo=UTC).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "datetime": ts,
                    "headline": "Apple beats",
                    "summary": "...",
                    "source": "Reuters",
                    "url": "https://example.com",
                    "category": "company news",
                }
            ],
        )

    src = FinnhubSource("k", client=_client(handler))
    out = src.company_news("aapl", start=date(2026, 5, 1), end=date(2026, 5, 2))
    assert len(out) == 1
    assert out[0].headline == "Apple beats"
    assert out[0].published_at == datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def test_rate_limit_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="too many")

    src = FinnhubSource("k", client=_client(handler))
    with pytest.raises(RateLimitError):
        src.earnings_calendar("aapl", start=date(2026, 1, 1), end=date(2026, 3, 1))


def test_non_200_raises_data_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="server error")

    src = FinnhubSource("k", client=_client(handler))
    with pytest.raises(DataSourceError):
        src.company_news("aapl", start=date(2026, 5, 1), end=date(2026, 5, 2))


def test_start_after_end_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    src = FinnhubSource("k", client=_client(handler))
    with pytest.raises(ValueError):
        src.earnings_calendar("aapl", start=date(2026, 3, 1), end=date(2026, 1, 1))
