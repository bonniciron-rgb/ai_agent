"""Tests for the macro regime classifier."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlmodel import Session

from ai_agent.db.models import Bar
from ai_agent.macro.regime_detector import (
    REGIMES,
    classify_macro_regime,
    compute_and_save,
)

_AS_OF = date(2026, 1, 1)


def _classify(**kwargs):
    defaults = {
        "as_of": _AS_OF,
        "spy_close": Decimal("450"),
        "spy_sma_50": Decimal("440"),
        "spy_sma_200": Decimal("420"),
        "vix_close": Decimal("15"),
    }
    defaults.update(kwargs)
    return classify_macro_regime(**defaults)


# ---------------------------------------------------------------------------
# Pure classifier tests
# ---------------------------------------------------------------------------


def test_crisis_when_vix_above_30():
    result = _classify(
        spy_close=Decimal("400"),
        spy_sma_50=Decimal("420"),
        spy_sma_200=Decimal("430"),
        vix_close=Decimal("35"),
    )
    assert result.regime == "crisis"
    assert any(">= 30" in n or "crisis" in n for n in result.notes)


def test_bear_when_below_smas_and_vix_elevated():
    result = _classify(
        spy_close=Decimal("380"),
        spy_sma_50=Decimal("400"),
        spy_sma_200=Decimal("420"),
        vix_close=Decimal("25"),
    )
    assert result.regime == "bear"


def test_correction_when_below_smas_but_vix_calm():
    result = _classify(
        spy_close=Decimal("380"),
        spy_sma_50=Decimal("400"),
        spy_sma_200=Decimal("420"),
        vix_close=Decimal("18"),
    )
    assert result.regime == "correction"


def test_bull_when_golden_cross_and_low_vix():
    result = _classify(
        spy_close=Decimal("450"),
        spy_sma_50=Decimal("440"),
        spy_sma_200=Decimal("420"),
        vix_close=Decimal("14"),
    )
    assert result.regime == "bull"


def test_bull_blocked_by_high_vix():
    # Golden cross structure but VIX=22 -- not calm enough for bull.
    # spy > sma50 > sma200 but VIX not < 20 so it won't be bull.
    # SPY=450, sma_50=440, sma_200=420 -> deviation from 200 = 30/420 ~7.1% > 5%
    # so it won't be sideways either -> mixed
    result = _classify(
        spy_close=Decimal("450"),
        spy_sma_50=Decimal("440"),
        spy_sma_200=Decimal("420"),
        vix_close=Decimal("22"),
    )
    assert result.regime != "bull"
    assert result.regime == "mixed"


def test_sideways_when_within_5pct():
    result = _classify(
        spy_close=Decimal("420"),
        spy_sma_50=Decimal("425"),
        spy_sma_200=Decimal("420"),
        vix_close=Decimal("18"),
    )
    assert result.regime == "sideways"


def test_mixed_default():
    # SPY above SMAs but VIX elevated, deviation > 5% from 200d
    result = _classify(
        spy_close=Decimal("460"),
        spy_sma_50=Decimal("440"),
        spy_sma_200=Decimal("420"),
        vix_close=Decimal("23"),
    )
    assert result.regime == "mixed"


def test_booleans_set_correctly():
    above = _classify(
        spy_close=Decimal("450"),
        spy_sma_50=Decimal("440"),
        spy_sma_200=Decimal("420"),
        vix_close=Decimal("14"),
    )
    assert above.spy_above_200sma is True
    assert above.spy_50_over_200sma is True

    below = _classify(
        spy_close=Decimal("380"),
        spy_sma_50=Decimal("400"),
        spy_sma_200=Decimal("420"),
        vix_close=Decimal("25"),
    )
    assert below.spy_above_200sma is False
    assert below.spy_50_over_200sma is False


def test_classification_includes_notes():
    cases = [
        (
            "crisis",
            {
                "vix_close": Decimal("35"),
                "spy_close": Decimal("400"),
                "spy_sma_50": Decimal("420"),
                "spy_sma_200": Decimal("430"),
            },
        ),
        (
            "bear",
            {
                "spy_close": Decimal("380"),
                "spy_sma_50": Decimal("400"),
                "spy_sma_200": Decimal("420"),
                "vix_close": Decimal("25"),
            },
        ),
        (
            "correction",
            {
                "spy_close": Decimal("380"),
                "spy_sma_50": Decimal("400"),
                "spy_sma_200": Decimal("420"),
                "vix_close": Decimal("18"),
            },
        ),
        (
            "bull",
            {
                "spy_close": Decimal("450"),
                "spy_sma_50": Decimal("440"),
                "spy_sma_200": Decimal("420"),
                "vix_close": Decimal("14"),
            },
        ),
        (
            "sideways",
            {
                "spy_close": Decimal("420"),
                "spy_sma_50": Decimal("425"),
                "spy_sma_200": Decimal("420"),
                "vix_close": Decimal("18"),
            },
        ),
        (
            "mixed",
            {
                "spy_close": Decimal("460"),
                "spy_sma_50": Decimal("440"),
                "spy_sma_200": Decimal("420"),
                "vix_close": Decimal("23"),
            },
        ),
    ]
    for regime_name, kwargs in cases:
        result = _classify(**kwargs)
        assert result.regime == regime_name
        assert len(result.notes) >= 1, f"Regime '{regime_name}' returned no notes"


def test_vix_sma_optional():
    result = _classify(vix_sma_20=None)
    assert result.vix_sma_20 is None
    assert result.regime in REGIMES


# ---------------------------------------------------------------------------
# Orchestration smoke test
# ---------------------------------------------------------------------------


def test_compute_and_save_smoke(in_memory_engine, monkeypatch):
    with Session(in_memory_engine) as session:
        for i in range(220):
            d = date(2026, 1, 1) + timedelta(days=i)
            session.add(
                Bar(
                    symbol="SPY",
                    trading_date=d,
                    open=Decimal("400"),
                    high=Decimal("405"),
                    low=Decimal("395"),
                    close=Decimal("400"),
                    volume=1_000_000,
                    source="test",
                )
            )
            session.add(
                Bar(
                    symbol="^VIX",
                    trading_date=d,
                    open=Decimal("18"),
                    high=Decimal("19"),
                    low=Decimal("17"),
                    close=Decimal("18"),
                    volume=0,
                    source="test",
                )
            )
        session.commit()

    monkeypatch.setattr("ai_agent.macro.regime_detector.ingest_bars", lambda *a, **kw: None)

    snap = compute_and_save(as_of=date(2026, 8, 8), engine=in_memory_engine)
    assert snap is not None
    assert snap.regime in REGIMES
