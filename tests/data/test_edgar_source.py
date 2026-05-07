from datetime import date

import httpx
import pytest

from ai_agent.data import DataSourceError, SymbolNotFoundError
from ai_agent.data.edgar_source import (
    EDGAR_TICKERS_URL,
    EdgarSource,
)

UA = "ai_agent/test (test@example.com)"

TICKER_PAYLOAD = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp."},
}

SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "form": ["10-K", "8-K", "10-Q", "DEF 14A"],
            "filingDate": ["2026-04-01", "2026-03-15", "2026-02-01", "2026-01-10"],
            "reportDate": ["2025-12-31", "", "2025-12-31", ""],
            "accessionNumber": [
                "0000320193-26-000001",
                "0000320193-26-000002",
                "0000320193-26-000003",
                "0000320193-26-000004",
            ],
            "primaryDocument": ["aapl-10k.htm", "form8k.htm", "aapl-10q.htm", "proxy.htm"],
        }
    }
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _both_endpoints(ticker_resp=TICKER_PAYLOAD, submissions_resp=SUBMISSIONS_PAYLOAD):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if EDGAR_TICKERS_URL in url:
            return httpx.Response(200, json=ticker_resp)
        if "submissions" in url:
            return httpx.Response(200, json=submissions_resp)
        return httpx.Response(404, text="unexpected url")

    return handler


def test_requires_user_agent_with_email() -> None:
    with pytest.raises(ValueError):
        EdgarSource("ai_agent/0.1")


def test_cik_for_known_symbol() -> None:
    src = EdgarSource(UA, client=_client(_both_endpoints()))
    assert src.cik_for("aapl") == "0000320193"


def test_cik_for_unknown_symbol_raises() -> None:
    src = EdgarSource(UA, client=_client(_both_endpoints()))
    with pytest.raises(SymbolNotFoundError):
        src.cik_for("ZZZZ")


def test_recent_filings_filters_to_default_forms() -> None:
    src = EdgarSource(UA, client=_client(_both_endpoints()))
    filings = src.recent_filings("AAPL")

    forms = {f.form for f in filings}
    assert forms == {"10-K", "8-K", "10-Q"}
    assert all(f.symbol == "AAPL" for f in filings)
    assert all(f.cik == "0000320193" for f in filings)


def test_recent_filings_respects_since_filter() -> None:
    src = EdgarSource(UA, client=_client(_both_endpoints()))
    filings = src.recent_filings("AAPL", since=date(2026, 3, 1))

    dates = [f.filing_date for f in filings]
    assert all(d >= date(2026, 3, 1) for d in dates)
    assert len(filings) == 2  # 10-K on 2026-04-01 and 8-K on 2026-03-15


def test_recent_filings_constructs_doc_url() -> None:
    src = EdgarSource(UA, client=_client(_both_endpoints()))
    filings = src.recent_filings("AAPL", forms=("10-K",))

    assert len(filings) == 1
    assert filings[0].primary_doc == "aapl-10k.htm"
    assert filings[0].primary_doc_url is not None
    assert "320193" in filings[0].primary_doc_url


def test_recent_filings_uses_user_agent_header() -> None:
    seen_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("user-agent", ""))
        url = str(request.url)
        if EDGAR_TICKERS_URL in url:
            return httpx.Response(200, json=TICKER_PAYLOAD)
        return httpx.Response(200, json=SUBMISSIONS_PAYLOAD)

    src = EdgarSource(UA, client=_client(handler))
    src.recent_filings("AAPL")

    assert any(UA in h for h in seen_headers)


def test_non_200_raises_data_source_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    src = EdgarSource(UA, client=_client(handler))
    with pytest.raises(DataSourceError):
        src.cik_for("AAPL")
