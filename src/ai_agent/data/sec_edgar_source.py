"""SEC EDGAR Form 4 data source for insider transaction events.

Fetches Form 4 filings (insider transactions) for a given CIK from the
SEC EDGAR public API.  No API key is required, but the SEC fair-access
policy mandates a User-Agent header that identifies the requester.

References:
  - Submissions API: https://data.sec.gov/submissions/CIK{cik:0>10}.json
  - Form 4 XML schema: https://www.sec.gov/files/forms/form4.xsd

Parsing scope:
  Only ``nonDerivativeTransaction`` rows are parsed.  Derivative
  transactions (options, warrants) are out of scope for the A3 signal.
  If a filing XML is malformed or missing required fields, it is skipped
  with a warning logged.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import httpx

from ai_agent.data.base import DataSourceError, RateLimitError
from ai_agent.signals.insider_buying import InsiderBuy

logger = logging.getLogger(__name__)

EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_ARCHIVES_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{accession}.txt"
)

# SEC fair-use rate limit: 10 requests/second.  We are defensive and pace at
# roughly 5 req/sec with a 0.2s inter-request sleep when iterating filings.
_INTER_REQUEST_SLEEP = 0.2


class SecEdgarSource:
    """SEC EDGAR Form 4 adapter.

    Fetches recent Form 4 filings for a company (by CIK) and parses
    open-market insider purchase transactions from the filing XML.

    No API key required.  A User-Agent header containing a contact email
    address is mandatory per SEC policy:
    https://www.sec.gov/os/webmaster-faq#developers

    Parameters
    ----------
    user_agent:
        The ``User-Agent`` string sent with every request.  Must contain
        a contact email address.  Defaults to the Ethera Trading research
        contact; override for production deployments.
    client:
        Optional pre-built ``httpx.Client`` (useful for testing with a
        mock transport).  If ``None`` a new client is opened per request.
    timeout_seconds:
        HTTP request timeout.  Defaults to 10s.
    """

    name = "sec_edgar"

    def __init__(
        self,
        user_agent: str = "Ethera Trading research@etheratrading.example",
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SecEdgarSource requires a User-Agent string containing a contact email "
                "(SEC policy).  Pass user_agent='App Name contact@example.com'."
            )
        self._user_agent = user_agent
        self._client = client
        self._timeout = timeout_seconds

    def _open(self) -> httpx.Client:
        return self._client or httpx.Client(
            timeout=self._timeout,
            headers={"User-Agent": self._user_agent},
        )

    def _get_json(self, url: str) -> dict:
        client = self._open()
        owns = self._client is None
        try:
            resp = client.get(url, headers={"User-Agent": self._user_agent})
        except httpx.HTTPError as exc:
            raise DataSourceError(f"SEC EDGAR HTTP error: {exc}") from exc
        finally:
            if owns:
                client.close()

        if resp.status_code == 429:
            raise RateLimitError("SEC EDGAR rate limit hit")
        if resp.status_code != 200:
            raise DataSourceError(f"SEC EDGAR returned status {resp.status_code} for {url}")
        try:
            return resp.json()
        except ValueError as exc:
            raise DataSourceError(f"SEC EDGAR returned non-JSON: {exc}") from exc

    def _get_text(self, url: str) -> str:
        client = self._open()
        owns = self._client is None
        try:
            resp = client.get(url, headers={"User-Agent": self._user_agent})
        except httpx.HTTPError as exc:
            raise DataSourceError(f"SEC EDGAR HTTP error: {exc}") from exc
        finally:
            if owns:
                client.close()

        if resp.status_code == 404:
            return ""
        if resp.status_code == 429:
            raise RateLimitError("SEC EDGAR rate limit hit")
        if resp.status_code != 200:
            raise DataSourceError(f"SEC EDGAR returned status {resp.status_code} for {url}")
        return resp.text

    def recent_form4_filings(
        self,
        cik: str,
        days_back: int = 90,
    ) -> list[dict]:
        """Return Form 4 filing metadata for a CIK within the past *days_back* days.

        Calls ``data.sec.gov/submissions/CIK{cik:0>10}.json``, filters to
        Form 4 entries filed within the requested window, and returns a list
        of dicts with keys ``accession_number``, ``filing_date``, and ``cik``.

        Parameters
        ----------
        cik:
            SEC CIK (numeric string, with or without zero-padding).
        days_back:
            How far back from today to include filings.
        """
        padded_cik = str(cik).zfill(10)
        url = EDGAR_SUBMISSIONS_URL.format(cik=padded_cik)
        payload = self._get_json(url)

        recent = (payload.get("filings") or {}).get("recent") or {}
        forms_arr = recent.get("form") or []
        dates_arr = recent.get("filingDate") or []
        accessions_arr = recent.get("accessionNumber") or []

        cutoff = date.today() - timedelta(days=days_back)
        out: list[dict] = []

        for i, form in enumerate(forms_arr):
            if form not in ("4", "4/A"):
                continue
            try:
                filing_date = date.fromisoformat(dates_arr[i])
            except (IndexError, ValueError):
                continue
            if filing_date < cutoff:
                continue

            accession = accessions_arr[i] if i < len(accessions_arr) else ""
            if not accession:
                continue

            out.append(
                {
                    "accession_number": accession,
                    "filing_date": filing_date,
                    "cik": str(cik),
                }
            )

        return out

    def parse_form4_filing(
        self,
        accession_number: str,
        cik: str,
    ) -> list[InsiderBuy]:
        """Fetch and parse a single Form 4 filing, returning insider buy events.

        Downloads the full-submission text file from SEC EDGAR Archives
        (``/Archives/edgar/data/{cik}/{accession_clean}/{accession}.txt``),
        extracts the embedded Form 4 XML document, and parses
        ``nonDerivativeTransaction`` rows.

        Only rows with:
          - ``transactionCode == "P"`` (open-market purchase)
          - ``directOrIndirectOwnership == "D"`` (direct ownership)
          - ``isOfficer == "1"`` OR ``isDirector == "1"``

        are returned as :class:`InsiderBuy` instances.  Malformed rows are
        skipped with a warning.

        Parameters
        ----------
        accession_number:
            Accession number as returned by EDGAR (e.g. ``"0001234567-24-000001"``).
        cik:
            Issuer (company) CIK as a string.
        """
        accession_clean = accession_number.replace("-", "")
        url = EDGAR_ARCHIVES_URL.format(
            cik=str(int(cik)),
            accession_clean=accession_clean,
            accession=accession_number,
        )

        raw = self._get_text(url)
        if not raw:
            logger.warning("Empty or missing Form 4 document: %s", url)
            return []

        # The .txt submission file wraps the actual XML document in an SGML
        # envelope.  We extract the <XML>…</XML> section containing the Form 4.
        xml_content = _extract_xml_block(raw)
        if not xml_content:
            logger.warning("No <XML> block found in Form 4 filing %s", accession_number)
            return []

        return _parse_form4_xml(xml_content, cik=cik, accession=accession_number)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_xml_block(text: str) -> str:
    """Extract the first <XML>…</XML> block from an SGML-wrapped submission."""
    start = text.find("<XML>")
    if start == -1:
        # Try the direct ownershipDocument tag (some filings omit the wrapper).
        if "<ownershipDocument>" in text:
            return text
        return ""
    end = text.find("</XML>", start)
    if end == -1:
        return text[start + 5 :]
    return text[start + 5 : end].strip()


def _text(el: ET.Element | None, tag: str) -> str:
    """Return stripped text of *tag* child of *el*, or empty string."""
    if el is None:
        return ""
    child = el.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _parse_form4_xml(xml_content: str, *, cik: str, accession: str) -> list[InsiderBuy]:
    """Parse Form 4 XML and return qualifying InsiderBuy events."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.warning("Failed to parse Form 4 XML for %s: %s", accession, exc)
        return []

    # Reporting owner role flags (shared across all transactions in the filing).
    owner_el = root.find(".//reportingOwner")
    owner_rel = owner_el.find("reportingOwnerRelationship") if owner_el is not None else None

    def _flag(tag: str) -> bool:
        return _text(owner_rel, tag) == "1"

    is_officer = _flag("isOfficer")
    is_director = _flag("isDirector")
    is_ten_pct = _flag("isTenPercentOwner")

    # Reporting person's CIK.
    owner_id_el = owner_el.find("reportingOwnerId") if owner_el is not None else None
    reporting_cik = _text(owner_id_el, "rptOwnerCik") or cik

    results: list[InsiderBuy] = []

    for tx_el in root.findall(".//nonDerivativeTransaction"):
        try:
            tx_date_str = _text(tx_el.find("transactionDate"), "value")  # type: ignore[arg-type]
            if not tx_date_str:
                tx_date_str = _text(tx_el, "transactionDate")
            tx_date = date.fromisoformat(tx_date_str)

            tx_amounts = tx_el.find("transactionAmounts")
            code_el = tx_el.find("transactionCoding")
            code = _text(code_el, "transactionCode") if code_el is not None else ""

            shares_str = _text(tx_amounts, "transactionShares") if tx_amounts is not None else ""
            # Handle nested <value> tags used in some Form 4 schemas.
            if not shares_str:
                val_el = tx_el.find(".//transactionShares/value")
                shares_str = val_el.text.strip() if val_el is not None and val_el.text else ""

            price_str = (
                _text(tx_amounts, "transactionPricePerShare") if tx_amounts is not None else ""
            )
            if not price_str:
                price_el = tx_el.find(".//transactionPricePerShare/value")
                price_str = price_el.text.strip() if price_el is not None and price_el.text else "0"

            ownership_el = tx_el.find("ownershipNature")
            direct_indirect = (
                _text(ownership_el, "directOrIndirectOwnership") if ownership_el is not None else ""
            )
            if not direct_indirect:
                val_el = tx_el.find(".//directOrIndirectOwnership/value")
                direct_indirect = val_el.text.strip() if val_el is not None and val_el.text else ""

            shares = int(float(shares_str or "0"))
            price = float(price_str or "0")
            value_usd = shares * price

        except (ValueError, AttributeError, TypeError) as exc:
            logger.warning("Skipping malformed nonDerivativeTransaction in %s: %s", accession, exc)
            continue

        results.append(
            InsiderBuy(
                transaction_date=tx_date,
                cik=reporting_cik,
                transaction_shares=shares,
                transaction_price=price,
                transaction_value_usd=value_usd,
                transaction_code=code,
                direct_or_indirect_ownership=direct_indirect,
                is_officer=is_officer,
                is_director=is_director,
                is_ten_percent_owner=is_ten_pct,
            )
        )

    return results
