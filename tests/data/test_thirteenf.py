"""Tests for the SEC 13F holdings fetcher (ai_agent.data.thirteenf)."""

import httpx

import ai_agent.data.thirteenf as t13
from ai_agent.data.thirteenf import Manager, _parse_holdings, latest_13f

INFO_TABLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <cusip>037833100</cusip>
    <value>60000000000</value>
    <shrsOrPrnAmt><sshPrnamt>300000000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <cusip>037833100</cusip>
    <value>15000000000</value>
    <shrsOrPrnAmt><sshPrnamt>75000000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>COCA COLA CO</nameOfIssuer>
    <cusip>191216100</cusip>
    <value>25000000000</value>
    <shrsOrPrnAmt><sshPrnamt>400000000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


def test_parse_holdings_merges_and_ranks() -> None:
    holdings = _parse_holdings(INFO_TABLE_XML)
    # The two Apple lots merge (60B + 15B = 75B); Coke 25B; total 100B.
    assert len(holdings) == 2
    assert holdings[0].issuer == "APPLE INC"
    assert holdings[0].value == 75_000_000_000
    assert holdings[0].pct == 0.75
    assert holdings[1].issuer == "COCA COLA CO"
    assert holdings[1].pct == 0.25


def test_parse_holdings_skips_zero_value() -> None:
    holdings = _parse_holdings(INFO_TABLE_XML.replace("25000000000", "0"))
    assert [h.issuer for h in holdings] == ["APPLE INC"]


def _mock_client(routes: dict[str, tuple[int, str]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, (status, body) in routes.items():
            if fragment in request.url.path:
                return httpx.Response(status, text=body)
        return httpx.Response(404, text="not found")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_latest_13f_full_flow() -> None:
    t13._cache.clear()
    submissions = (
        '{"filings": {"recent": {'
        '"form": ["13F-HR"], '
        '"accessionNumber": ["0000950123-26-001234"], '
        '"reportDate": ["2026-03-31"]}}}'
    )
    index = '{"directory": {"item": [{"name": "form13fInfoTable.xml"}]}}'
    client = _mock_client(
        {
            "/submissions/": (200, submissions),
            "/index.json": (200, index),
            "InfoTable.xml": (200, INFO_TABLE_XML),
        }
    )
    report = latest_13f(Manager("Test Fund", "0001067983"), client=client)
    assert report.error is None
    assert report.period_of_report == "2026-03-31"
    assert report.holdings[0].issuer == "APPLE INC"


def test_latest_13f_no_filing_reports_error() -> None:
    t13._cache.clear()
    client = _mock_client({"/submissions/": (200, '{"filings": {"recent": {"form": ["8-K"]}}}')})
    report = latest_13f(Manager("Test Fund", "0009999999"), client=client)
    assert report.error == "no 13F-HR filing found"
    assert report.holdings == []
