"""Tests for the per-proposal risk score (ai_agent.risk.scoring)."""

from decimal import Decimal

from ai_agent.risk.scoring import score_proposal


def test_low_risk_small_calm_tight() -> None:
    rs = score_proposal(
        notional_gbp=Decimal("100"),  # 1% of NAV
        nav=Decimal("10000"),
        price=Decimal("200"),
        atr=Decimal("2"),  # 1% ATR
        stop_price=Decimal("194"),  # 3% stop
    )
    assert rs.score == 1
    assert "Very low" in rs.reason


def test_high_risk_large_volatile_wide() -> None:
    rs = score_proposal(
        notional_gbp=Decimal("450"),  # 4.5% of NAV
        nav=Decimal("10000"),
        price=Decimal("200"),
        atr=Decimal("12"),  # 6% ATR
        stop_price=Decimal("170"),  # 15% stop
    )
    assert rs.score == 5
    assert "Very high" in rs.reason


def test_missing_stop_raises_risk() -> None:
    with_stop = score_proposal(
        notional_gbp=Decimal("100"),
        nav=Decimal("10000"),
        price=Decimal("200"),
        atr=Decimal("2"),
        stop_price=Decimal("194"),
    )
    without_stop = score_proposal(
        notional_gbp=Decimal("100"),
        nav=Decimal("10000"),
        price=Decimal("200"),
        atr=Decimal("2"),
        stop_price=None,
    )
    assert without_stop.score > with_stop.score
    assert "no stop set" in without_stop.reason


def test_missing_atr_is_handled() -> None:
    rs = score_proposal(
        notional_gbp=Decimal("100"),
        nav=Decimal("10000"),
        price=Decimal("200"),
        atr=None,
        stop_price=Decimal("194"),
    )
    assert 1 <= rs.score <= 5
    assert "ATR unavailable" in rs.reason


def test_score_stays_in_range_with_no_data() -> None:
    rs = score_proposal(
        notional_gbp=Decimal("0"),
        nav=Decimal("0"),
        price=Decimal("0"),
        atr=None,
        stop_price=None,
    )
    assert 1 <= rs.score <= 5
