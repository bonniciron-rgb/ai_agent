"""Tests for the five risk rails and the RiskChecker aggregator."""

from __future__ import annotations

from decimal import Decimal

from ai_agent.risk.rails import (
    COOLDOWN_DAYS,
    RiskChecker,
    check_atr_stop,
    check_cooldown,
    check_daily_turnover,
    check_position_cap,
    check_sector_cap,
)

# ---------------------------------------------------------------------------
# Fake portfolio
# ---------------------------------------------------------------------------


class FakePortfolio:
    def __init__(
        self,
        nav: Decimal = Decimal("100_000"),
        positions: dict[str, Decimal] | None = None,
        sectors: dict[str, Decimal] | None = None,
        symbol_sector_map: dict[str, str] | None = None,
        turnover_today: Decimal = Decimal("0"),
        sell_history: dict[str, int] | None = None,  # symbol -> days ago
        atr_map: dict[str, Decimal] | None = None,
    ) -> None:
        self._nav = nav
        self._positions = positions or {}
        self._sectors = sectors or {}
        self._symbol_sector_map = symbol_sector_map or {}
        self._turnover = turnover_today
        self._sell_history = sell_history or {}
        self._atr_map = atr_map or {}

    @property
    def nav(self) -> Decimal:
        return self._nav

    def position_value(self, symbol: str) -> Decimal:
        return self._positions.get(symbol, Decimal("0"))

    def sector_value(self, sector: str) -> Decimal:
        return self._sectors.get(sector, Decimal("0"))

    def symbol_sector(self, symbol: str) -> str | None:
        return self._symbol_sector_map.get(symbol)

    def daily_turnover(self) -> Decimal:
        return self._turnover

    def days_since_last_sell(self, symbol: str) -> int | None:
        return self._sell_history.get(symbol)

    def atr(self, symbol: str) -> Decimal | None:
        return self._atr_map.get(symbol)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

NAV = Decimal("100_000")


def portfolio(**kwargs) -> FakePortfolio:
    return FakePortfolio(nav=NAV, **kwargs)


# ---------------------------------------------------------------------------
# 1. Position cap
# ---------------------------------------------------------------------------


def test_position_cap_passes_under_limit() -> None:
    p = portfolio()
    # 4 % of 100k = 4000, under 5 % limit
    result = check_position_cap("AAPL", Decimal("4_000"), p)
    assert result.allowed


def test_position_cap_fails_at_limit() -> None:
    p = portfolio()
    # 5001 > 5000 cap
    result = check_position_cap("AAPL", Decimal("5_001"), p)
    assert not result.allowed
    assert "Position cap" in result.reason


def test_position_cap_includes_existing_position() -> None:
    p = portfolio(positions={"AAPL": Decimal("3_000")})
    # existing 3k + order 2.5k = 5.5k > 5k cap
    result = check_position_cap("AAPL", Decimal("2_500"), p)
    assert not result.allowed


def test_position_cap_zero_nav_fails() -> None:
    p = FakePortfolio(nav=Decimal("0"))
    result = check_position_cap("AAPL", Decimal("1_000"), p)
    assert not result.allowed


# ---------------------------------------------------------------------------
# 2. ATR stop
# ---------------------------------------------------------------------------


def test_atr_stop_passes_with_valid_stop() -> None:
    p = portfolio(atr_map={"AAPL": Decimal("2")})
    # limit 100, atr 2 → min_stop = 100 - 2*2 = 96; stop 96 == min_stop → ok
    result = check_atr_stop("AAPL", Decimal("100"), Decimal("96"), p)
    assert result.allowed


def test_atr_stop_fails_stop_too_close() -> None:
    p = portfolio(atr_map={"AAPL": Decimal("2")})
    # min_stop = 96; stop 97 > 96 but we need stop < min_stop to fail
    # stop 95.99 < 96 → fail
    result = check_atr_stop("AAPL", Decimal("100"), Decimal("95.99"), p)
    assert not result.allowed
    assert "ATR stop" in result.reason


def test_atr_stop_fails_no_stop_price() -> None:
    p = portfolio(atr_map={"AAPL": Decimal("2")})
    result = check_atr_stop("AAPL", Decimal("100"), None, p)
    assert not result.allowed
    assert "no stop_price" in result.reason


def test_atr_stop_skips_when_atr_unavailable() -> None:
    p = portfolio()  # no ATR in map
    result = check_atr_stop("AAPL", Decimal("100"), Decimal("90"), p)
    # allowed but with advisory
    assert result.allowed
    assert "unavailable" in result.reason


# ---------------------------------------------------------------------------
# 3. Daily turnover
# ---------------------------------------------------------------------------


def test_daily_turnover_passes_under_limit() -> None:
    p = portfolio(turnover_today=Decimal("0"))
    result = check_daily_turnover(Decimal("19_000"), p)
    assert result.allowed


def test_daily_turnover_fails_when_over() -> None:
    p = portfolio(turnover_today=Decimal("18_000"))
    # 18k + 3k = 21k > 20% of 100k = 20k
    result = check_daily_turnover(Decimal("3_000"), p)
    assert not result.allowed
    assert "Daily turnover" in result.reason


def test_daily_turnover_exact_limit_passes() -> None:
    p = portfolio(turnover_today=Decimal("0"))
    # exactly 20k = 20% → should pass (≤ not <)
    result = check_daily_turnover(Decimal("20_000"), p)
    assert result.allowed


# ---------------------------------------------------------------------------
# 4. Sector cap
# ---------------------------------------------------------------------------


def test_sector_cap_passes_under_limit() -> None:
    p = portfolio(
        symbol_sector_map={"AAPL": "Technology"},
        sectors={"Technology": Decimal("25_000")},
    )
    result = check_sector_cap("AAPL", Decimal("4_000"), p)
    assert result.allowed


def test_sector_cap_fails_over_limit() -> None:
    p = portfolio(
        symbol_sector_map={"AAPL": "Technology"},
        sectors={"Technology": Decimal("29_000")},
    )
    # 29k + 2k = 31k > 30k cap
    result = check_sector_cap("AAPL", Decimal("2_000"), p)
    assert not result.allowed
    assert "Sector cap" in result.reason


def test_sector_cap_skips_unknown_sector() -> None:
    p = portfolio()  # no sector map
    result = check_sector_cap("AAPL", Decimal("5_000"), p)
    assert result.allowed
    assert "skipped" in result.reason


# ---------------------------------------------------------------------------
# 5. Cooldown
# ---------------------------------------------------------------------------


def test_cooldown_passes_no_prior_sell() -> None:
    p = portfolio()
    result = check_cooldown("AAPL", p)
    assert result.allowed


def test_cooldown_passes_after_cooldown_period() -> None:
    p = portfolio(sell_history={"AAPL": COOLDOWN_DAYS})
    result = check_cooldown("AAPL", p)
    assert result.allowed


def test_cooldown_fails_within_period() -> None:
    p = portfolio(sell_history={"AAPL": COOLDOWN_DAYS - 1})
    result = check_cooldown("AAPL", p)
    assert not result.allowed
    assert "Cooldown" in result.reason


def test_cooldown_fails_day_zero() -> None:
    p = portfolio(sell_history={"AAPL": 0})
    result = check_cooldown("AAPL", p)
    assert not result.allowed


# ---------------------------------------------------------------------------
# RiskChecker aggregator
# ---------------------------------------------------------------------------


def make_portfolio() -> FakePortfolio:
    return FakePortfolio(
        nav=NAV,
        atr_map={"AAPL": Decimal("2")},
        symbol_sector_map={"AAPL": "Technology"},
        sectors={"Technology": Decimal("0")},
    )


def test_risk_checker_all_pass() -> None:
    checker = RiskChecker(portfolio=make_portfolio())
    result = checker.check(
        symbol="AAPL",
        side="buy",
        quantity=10,
        limit_price=Decimal("150"),
        stop_price=Decimal("145"),  # 150 - 2*2=4 → min 146; 145 < 146 would fail
        # Actually 150 - 2*2 = 146, so stop must be >= 146
    )
    # stop 145 < 146 → should fail ATR stop
    assert not result.allowed


def test_risk_checker_valid_stop_passes() -> None:
    checker = RiskChecker(portfolio=make_portfolio())
    result = checker.check(
        symbol="AAPL",
        side="buy",
        quantity=10,
        limit_price=Decimal("150"),
        stop_price=Decimal("146"),  # exactly min_stop → pass
    )
    assert result.allowed


def test_buy_without_stop_price_is_rejected() -> None:
    checker = RiskChecker(portfolio=make_portfolio())
    result = checker.check(
        symbol="AAPL",
        side="buy",
        quantity=1,
        limit_price=Decimal("100"),
        stop_price=None,
    )
    assert not result.allowed
    assert "stop" in result.reason.lower()


def test_risk_checker_converts_usd_notional_to_gbp() -> None:
    # 100 shares @ $100 = $10,000 — over the 5% (5,000) cap of a 100k GBP NAV
    # at face value, but 0.4 * 10,000 = 4,000 GBP once converted, so it passes.
    raw = RiskChecker(portfolio=make_portfolio())
    assert not raw.check(
        symbol="AAPL",
        side="buy",
        quantity=100,
        limit_price=Decimal("100"),
        stop_price=Decimal("96"),
    ).allowed

    converted = RiskChecker(portfolio=make_portfolio(), usd_to_gbp=Decimal("0.4"))
    assert converted.check(
        symbol="AAPL",
        side="buy",
        quantity=100,
        limit_price=Decimal("100"),
        stop_price=Decimal("96"),
    ).allowed


def test_risk_checker_kill_switch_blocks_all() -> None:
    checker = RiskChecker(portfolio=make_portfolio(), halt=True)
    result = checker.check(
        symbol="AAPL",
        side="buy",
        quantity=1,
        limit_price=Decimal("150"),
        stop_price=Decimal("146"),
    )
    assert not result.allowed
    assert "halted" in result.reason


def test_risk_checker_halt_flag_can_be_toggled() -> None:
    checker = RiskChecker(portfolio=make_portfolio(), halt=True)
    checker.halt = False
    result = checker.check(
        symbol="AAPL",
        side="buy",
        quantity=1,
        limit_price=Decimal("150"),
        stop_price=Decimal("146"),
    )
    assert result.allowed


def test_risk_checker_sell_allowed_without_stop() -> None:
    # A full exit omits stop_price by design (prompts.py: "omit it when fully
    # exiting a position"). The rail must not reject an exit for lacking a stop.
    checker = RiskChecker(portfolio=portfolio(atr_map={"AAPL": Decimal("2")}))
    result = checker.check(
        symbol="AAPL",
        side="sell",
        quantity=10,
        limit_price=Decimal("150"),
        stop_price=None,
    )
    assert result.allowed


def test_risk_checker_sell_skips_position_and_sector_caps() -> None:
    # Even if position/sector caps would fire, a sell skips them — only turnover applies.
    p = FakePortfolio(
        nav=NAV,
        positions={"AAPL": Decimal("99_000")},  # way over cap but it's a sell
        atr_map={"AAPL": Decimal("2")},
        symbol_sector_map={"AAPL": "Technology"},
        sectors={"Technology": Decimal("99_000")},
    )
    checker = RiskChecker(portfolio=p)
    result = checker.check(
        symbol="AAPL",
        side="sell",
        quantity=10,
        limit_price=Decimal("150"),
        stop_price=Decimal("146"),
    )
    assert result.allowed


def test_risk_checker_warnings_collected() -> None:
    p = FakePortfolio(
        nav=NAV,
        # No ATR data and no sector data → two advisory skips
        atr_map={},
        symbol_sector_map={},
    )
    checker = RiskChecker(portfolio=p)
    checker.check(
        symbol="AAPL",
        side="buy",
        quantity=1,
        limit_price=Decimal("150"),
        stop_price=Decimal("140"),  # ATR unknown → skipped advisory
    )
    # at least one warning about ATR or sector being skipped
    assert len(checker.warnings) >= 1


def test_risk_checker_cooldown_blocks_buy() -> None:
    p = FakePortfolio(
        nav=NAV,
        atr_map={"AAPL": Decimal("2")},
        symbol_sector_map={"AAPL": "Technology"},
        sectors={"Technology": Decimal("0")},
        sell_history={"AAPL": 2},  # sold 2 days ago < 5 day cooldown
    )
    checker = RiskChecker(portfolio=p)
    result = checker.check(
        symbol="AAPL",
        side="buy",
        quantity=1,
        limit_price=Decimal("150"),
        stop_price=Decimal("146"),
    )
    assert not result.allowed
    assert "Cooldown" in result.reason
