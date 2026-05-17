"""SEC EDGAR 13F holdings — institutional "smart money" fetcher.

Pulls a fund manager's most recent 13F-HR filing (the quarterly disclosure of
long US-equity holdings) from EDGAR, so the agent can weigh what widely-followed
investors hold. Mirrors ``lib/thirteenf.ts`` (the /leaders page).

13F data only changes once a quarter, so successful results are cached for the
process lifetime.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0)
_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}"


@dataclass(frozen=True)
class Manager:
    name: str
    cik: str  # 10-digit zero-padded


@dataclass(frozen=True)
class Holding:
    issuer: str
    cusip: str
    value: float  # USD, as reported in the filing
    pct: float  # share of the manager's 13F portfolio (0..1)


@dataclass
class Report:
    manager: str
    cik: str
    period_of_report: str | None = None
    holdings: list[Holding] = field(default_factory=list)
    error: str | None = None


# Widely-followed institutional managers, by SEC CIK.
MANAGERS: list[Manager] = [
    Manager("Berkshire Hathaway — Warren Buffett", "0001067983"),
    Manager("Scion Asset Management — Michael Burry", "0001649339"),
    Manager("Pershing Square — Bill Ackman", "0001336528"),
]

# Process-lifetime cache: CIK -> Report (13F data only changes quarterly).
_cache: dict[str, Report] = {}


def _user_agent() -> str:
    from ai_agent.settings import get_settings

    return get_settings().edgar_user_agent


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def latest_13f(manager: Manager, *, client: httpx.Client | None = None) -> Report:
    """Return *manager*'s latest 13F-HR holdings; cached per process on success."""
    if manager.cik in _cache:
        return _cache[manager.cik]
    report = _fetch(manager, client)
    if report.error is None:
        _cache[manager.cik] = report
    return report


def _fetch(manager: Manager, client: httpx.Client | None) -> Report:
    own = client is None
    cl = client or httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _user_agent()})
    try:
        subs = cl.get(_SUBMISSIONS.format(cik=manager.cik))
        if subs.status_code != 200:
            return Report(manager.name, manager.cik, error=f"submissions HTTP {subs.status_code}")
        recent = (subs.json().get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        idx = next((i for i, f in enumerate(forms) if f in ("13F-HR", "13F-HR/A")), None)
        if idx is None:
            return Report(manager.name, manager.cik, error="no 13F-HR filing found")

        accession = (recent.get("accessionNumber") or [])[idx]
        period = (recent.get("reportDate") or [])[idx] if recent.get("reportDate") else None
        base = _ARCHIVE.format(cik=str(int(manager.cik)), acc=accession.replace("-", ""))

        index = cl.get(f"{base}/index.json")
        if index.status_code != 200:
            return Report(
                manager.name, manager.cik, period, error=f"index HTTP {index.status_code}"
            )
        items = (index.json().get("directory") or {}).get("item") or []
        info_name = next(
            (
                it["name"]
                for it in items
                if isinstance(it.get("name"), str)
                and "info" in it["name"].lower()
                and "table" in it["name"].lower()
                and it["name"].lower().endswith(".xml")
            ),
            None,
        )
        if not info_name:
            return Report(manager.name, manager.cik, period, error="no info table in filing")

        xml = cl.get(f"{base}/{info_name}")
        if xml.status_code != 200:
            return Report(
                manager.name, manager.cik, period, error=f"info table HTTP {xml.status_code}"
            )
        return Report(manager.name, manager.cik, period, holdings=_parse_holdings(xml.text))
    except Exception as exc:  # network failure, XML parse error, …
        logger.warning("13F fetch failed for %s: %s", manager.name, exc)
        return Report(manager.name, manager.cik, error=str(exc))
    finally:
        if own:
            cl.close()


def _parse_holdings(xml: str) -> list[Holding]:
    """Parse a 13F information-table XML into merged, value-ranked holdings."""
    # Encode to bytes: ElementTree rejects str input carrying an XML encoding
    # declaration, which EDGAR's information tables always include.
    root = ET.fromstring(xml.encode("utf-8"))
    merged: dict[str, dict] = {}
    for el in root.iter():
        if _localname(el.tag) != "infoTable":
            continue
        fields: dict[str, str] = {}
        for child in el.iter():
            if child.text and child.text.strip():
                fields[_localname(child.tag)] = child.text.strip()
        try:
            value = float(fields.get("value", "0"))
        except ValueError:
            continue
        if value <= 0:
            continue
        issuer = fields.get("nameOfIssuer", "—")
        cusip = fields.get("cusip", "")
        key = cusip or issuer
        if key in merged:
            merged[key]["value"] += value
        else:
            merged[key] = {"issuer": issuer, "cusip": cusip, "value": value}

    total = sum(h["value"] for h in merged.values())
    holdings = [
        Holding(
            issuer=h["issuer"],
            cusip=h["cusip"],
            value=h["value"],
            pct=(h["value"] / total) if total > 0 else 0.0,
        )
        for h in merged.values()
    ]
    holdings.sort(key=lambda h: h.value, reverse=True)
    return holdings
