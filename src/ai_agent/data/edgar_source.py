from __future__ import annotations

from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel

from ai_agent.data.base import DataSourceError, RateLimitError, SymbolNotFoundError

EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


class Filing(BaseModel):
    symbol: str
    cik: str
    form: str
    filing_date: date
    period_of_report: date | None = None
    accession_number: str
    primary_doc: str | None = None
    primary_doc_url: str | None = None


class EdgarSource:
    """SEC EDGAR adapter for recent filings.

    Free, no API key, but a meaningful User-Agent is required by SEC policy.
    Set EDGAR_USER_AGENT in env (defaults configured in settings.py).
    """

    name = "edgar"

    def __init__(
        self,
        user_agent: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "EdgarSource requires a User-Agent string containing a contact email "
                "(SEC policy). Set EDGAR_USER_AGENT in your environment."
            )
        self._user_agent = user_agent
        self._client = client
        self._timeout = timeout_seconds
        self._cik_cache: dict[str, str] | None = None

    def _open(self) -> httpx.Client:
        return self._client or httpx.Client(
            timeout=self._timeout,
            headers={"User-Agent": self._user_agent},
        )

    def _get_json(self, url: str) -> Any:
        client = self._open()
        owns = self._client is None
        try:
            resp = client.get(url, headers={"User-Agent": self._user_agent})
        except httpx.HTTPError as e:
            raise DataSourceError(f"edgar HTTP error: {e}") from e
        finally:
            if owns:
                client.close()

        if resp.status_code == 429:
            raise RateLimitError("edgar rate limit hit")
        if resp.status_code != 200:
            raise DataSourceError(f"edgar returned status {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise DataSourceError(f"edgar returned non-JSON: {e}") from e

    def _load_ticker_to_cik(self) -> dict[str, str]:
        if self._cik_cache is not None:
            return self._cik_cache
        payload = self._get_json(EDGAR_TICKERS_URL)
        mapping: dict[str, str] = {}
        for row in payload.values() if isinstance(payload, dict) else []:
            ticker = (row.get("ticker") or "").upper()
            cik_int = row.get("cik_str")
            if ticker and cik_int is not None:
                mapping[ticker] = str(cik_int).zfill(10)
        self._cik_cache = mapping
        return mapping

    def cik_for(self, symbol: str) -> str:
        mapping = self._load_ticker_to_cik()
        cik = mapping.get(symbol.upper())
        if not cik:
            raise SymbolNotFoundError(f"no EDGAR CIK for symbol {symbol!r}")
        return cik

    def recent_filings(
        self,
        symbol: str,
        *,
        forms: tuple[str, ...] = ("10-K", "10-Q", "8-K"),
        since: date | None = None,
        limit: int = 25,
    ) -> list[Filing]:
        cik = self.cik_for(symbol)
        payload = self._get_json(EDGAR_SUBMISSIONS_URL.format(cik=cik))

        recent = (payload.get("filings") or {}).get("recent") or {}
        forms_arr = recent.get("form") or []
        dates_arr = recent.get("filingDate") or []
        report_dates = recent.get("reportDate") or []
        accessions = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []

        out: list[Filing] = []
        for i, form in enumerate(forms_arr):
            if forms and form not in forms:
                continue
            try:
                filing_date = date.fromisoformat(dates_arr[i])
            except (IndexError, ValueError):
                continue
            if since and filing_date < since:
                continue

            try:
                period = date.fromisoformat(report_dates[i]) if report_dates[i] else None
            except (IndexError, ValueError):
                period = None

            accession = accessions[i] if i < len(accessions) else ""
            primary = primary_docs[i] if i < len(primary_docs) else None
            doc_url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(cik)}/{accession.replace('-', '')}/{primary}"
                if primary and accession
                else None
            )

            out.append(
                Filing(
                    symbol=symbol.upper(),
                    cik=cik,
                    form=form,
                    filing_date=filing_date,
                    period_of_report=period,
                    accession_number=accession,
                    primary_doc=primary,
                    primary_doc_url=doc_url,
                )
            )
            if len(out) >= limit:
                break
        return out
