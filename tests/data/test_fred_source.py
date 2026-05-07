from datetime import date
from decimal import Decimal

import httpx
import pytest

from ai_agent.data import DataSourceError, RateLimitError, SymbolNotFoundError
from ai_agent.data.fred_source import FredSource


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_requires_api_key() -> None:
    with pytest.raises(ValueError):
        FredSource("")


def test_series_parses_observations() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "observations": [
                    {"date": "2026-04-01", "value": "4.25"},
                    {"date": "2026-04-02", "value": "4.27"},
                    {"date": "2026-04-03", "value": "."},
                ]
            },
        )

    src = FredSource("k", client=_client(handler))
    out = src.series("DGS10", start=date(2026, 4, 1), end=date(2026, 4, 30))

    assert "api_key=k" in captured["url"]
    assert "file_type=json" in captured["url"]
    assert "series_id=DGS10" in captured["url"]
    assert len(out) == 3
    assert out[0].observation_date == date(2026, 4, 1)
    assert out[0].value == Decimal("4.25")
    assert out[2].value is None  # FRED uses "." for missing


def test_series_works_without_date_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": []})

    src = FredSource("k", client=_client(handler))
    assert src.series("DGS10") == []


def test_rate_limit_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="too many")

    src = FredSource("k", client=_client(handler))
    with pytest.raises(RateLimitError):
        src.series("DGS10")


def test_400_series_does_not_exist_raises_symbol_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="The series does not exist.")

    src = FredSource("k", client=_client(handler))
    with pytest.raises(SymbolNotFoundError):
        src.series("ZZZZZ")


def test_other_400_raises_data_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    src = FredSource("k", client=_client(handler))
    with pytest.raises(DataSourceError):
        src.series("DGS10")


def test_malformed_observation_raises_data_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": [{"value": "1.0"}]})  # no date

    src = FredSource("k", client=_client(handler))
    with pytest.raises(DataSourceError):
        src.series("DGS10")
