"""GBP foreign-exchange conversion for risk math.

T212 reports account NAV in the account currency (GBP), but instrument
prices come in their own currency — USD for US stocks, GBX (pence) for many
London listings. Risk caps compare order/position notionals against NAV, so
every notional must first be expressed in GBP.

Rates come from frankfurter.app (free, no API key, ECB data) and are cached
for the process lifetime — FX moves far too little over a single daily run
to matter for 5% / 20% / 30% risk caps.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

logger = logging.getLogger(__name__)

_FX_URL = "https://api.frankfurter.app/latest"
_TIMEOUT = httpx.Timeout(10.0)

# Process-lifetime cache: {currency: units of that currency per 1 GBP}.
_rates_cache: dict[str, Decimal] | None = None


def get_gbp_rates() -> dict[str, Decimal]:
    """Return ``{currency: units-per-GBP}`` (e.g. ``{"USD": Decimal("1.27")}``).

    Cached for the process lifetime. Returns ``{}`` if the rate service is
    unreachable, so callers fall back to leaving amounts unconverted.
    """
    global _rates_cache
    if _rates_cache is not None:
        return _rates_cache
    try:
        resp = httpx.get(_FX_URL, params={"base": "GBP"}, timeout=_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json().get("rates", {})
        _rates_cache = {str(k).upper(): Decimal(str(v)) for k, v in raw.items() if v}
    except Exception:
        logger.warning("FX rates unavailable — notionals will not be converted")
        _rates_cache = {}
    return _rates_cache


def to_gbp(
    amount: Decimal,
    currency: str,
    rates: dict[str, Decimal] | None = None,
) -> Decimal:
    """Convert *amount*, expressed in *currency*, to GBP.

    ``GBP`` is unchanged; ``GBX``/``GBp`` (pence) is divided by 100 (a unit,
    not an FX rate); any other currency is divided by its GBP rate. An
    unknown currency or missing rate leaves the amount unconverted.
    """
    c = (currency or "").strip()
    cu = c.upper()
    if cu == "GBX" or c == "GBp":
        return amount / 100
    if not cu or cu == "GBP":
        return amount
    if rates is None:
        rates = get_gbp_rates()
    rate = rates.get(cu)
    return amount / rate if rate and rate > 0 else amount
