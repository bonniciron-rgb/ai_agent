"""Tests for GBP FX conversion (ai_agent.broker.fx)."""

from decimal import Decimal

from ai_agent.broker.fx import to_gbp

RATES = {"USD": Decimal("1.25"), "EUR": Decimal("1.20")}


def test_gbp_is_unchanged() -> None:
    assert to_gbp(Decimal("100"), "GBP", RATES) == Decimal("100")


def test_gbx_pence_divided_by_100() -> None:
    assert to_gbp(Decimal("9450"), "GBX", RATES) == Decimal("94.5")
    assert to_gbp(Decimal("9450"), "GBp", RATES) == Decimal("94.5")


def test_foreign_currency_converted_by_rate() -> None:
    # 1 GBP = 1.25 USD, so 125 USD = 100 GBP.
    assert to_gbp(Decimal("125"), "USD", RATES) == Decimal("100")
    assert to_gbp(Decimal("120"), "EUR", RATES) == Decimal("100")


def test_unknown_currency_or_missing_rate_unchanged() -> None:
    assert to_gbp(Decimal("100"), "JPY", RATES) == Decimal("100")
    assert to_gbp(Decimal("100"), "", RATES) == Decimal("100")
