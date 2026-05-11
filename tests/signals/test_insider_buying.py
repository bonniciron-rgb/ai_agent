"""Tests for InsiderBuyingSignal (A3 alpha signal)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from ai_agent.signals.base import SignalContext
from ai_agent.signals.insider_buying import InsiderBuy, InsiderBuyingSignal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(n: int = 30, start: date | None = None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame; prices are flat (signal ignores them)."""
    start = start or date(2024, 1, 2)
    dates = [start + timedelta(days=i) for i in range(n)]
    closes = [100.0] * n
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * n,
        },
        index=pd.Index(dates, name="trading_date"),
    )


def _ctx(as_of: date, symbol: str = "AAPL") -> SignalContext:
    bars = _make_bars(start=as_of - timedelta(days=29))
    return SignalContext(symbol=symbol, as_of=as_of, bars=bars)


def _buy(
    *,
    transaction_date: date,
    cik: str = "CIK001",
    shares: int = 1_000,
    price: float = 100.0,
    value_usd: float | None = None,
    code: str = "P",
    direct: str = "D",
    is_officer: bool = True,
    is_director: bool = False,
    is_ten_pct: bool = False,
) -> InsiderBuy:
    return InsiderBuy(
        transaction_date=transaction_date,
        cik=cik,
        transaction_shares=shares,
        transaction_price=price,
        transaction_value_usd=value_usd if value_usd is not None else shares * price,
        transaction_code=code,
        direct_or_indirect_ownership=direct,
        is_officer=is_officer,
        is_director=is_director,
        is_ten_percent_owner=is_ten_pct,
    )


# ---------------------------------------------------------------------------
# TestSufficientBuyingGoesLong
# ---------------------------------------------------------------------------


class TestSufficientBuyingGoesLong:
    """2+ distinct insiders, combined >= $50k, within window → score 1.0."""

    def test_two_officers_qualify(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=30_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK002", value_usd=25_000.0),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0

    def test_note_contains_symbol_and_count(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=30_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK002", value_usd=25_000.0),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.notes
        note = result.notes[0]
        assert "AAPL" in note
        assert "2" in note

    def test_director_and_officer_both_count(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=10),
                cik="CIK001",
                value_usd=30_000.0,
                is_officer=True,
                is_director=False,
            ),
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK002",
                value_usd=25_000.0,
                is_officer=False,
                is_director=True,
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0

    def test_exactly_at_value_threshold_qualifies(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=25_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK002", value_usd=25_000.0),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events}, min_total_value_usd=50_000.0)
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestSingleInsiderIsFlat
# ---------------------------------------------------------------------------


class TestSingleInsiderIsFlat:
    """Only 1 distinct insider regardless of value → score 0.0."""

    def test_single_large_buy_is_flat(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK001",
                value_usd=500_000.0,
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_same_cik_twice_counts_as_one(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=30_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK001", value_usd=30_000.0),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestLowValueIsFlat
# ---------------------------------------------------------------------------


class TestLowValueIsFlat:
    """Multiple buyers but combined value < threshold → score 0.0."""

    def test_two_buyers_below_threshold(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=10_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK002", value_usd=15_000.0),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events}, min_total_value_usd=50_000.0)
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_note_mentions_threshold(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=5_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK002", value_usd=5_000.0),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0
        assert result.notes


# ---------------------------------------------------------------------------
# TestStaleEventsAreFlat
# ---------------------------------------------------------------------------


class TestStaleEventsAreFlat:
    """Events outside the lookback window → score 0.0."""

    def test_events_older_than_lookback_ignored(self):
        as_of = date(2024, 4, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=91),
                cik="CIK001",
                value_usd=30_000.0,
            ),
            _buy(
                transaction_date=as_of - timedelta(days=95),
                cik="CIK002",
                value_usd=30_000.0,
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events}, lookback_days=90)
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_future_events_are_ignored(self):
        as_of = date(2024, 4, 1)
        events = [
            _buy(
                transaction_date=as_of + timedelta(days=5),
                cik="CIK001",
                value_usd=30_000.0,
            ),
            _buy(
                transaction_date=as_of + timedelta(days=10),
                cik="CIK002",
                value_usd=30_000.0,
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestNonBuyTransactionsIgnored
# ---------------------------------------------------------------------------


class TestNonBuyTransactionsIgnored:
    """Sale / option-exercise / award rows are filtered out."""

    def test_sale_code_s_is_ignored(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=10),
                cik="CIK001",
                value_usd=30_000.0,
                code="S",  # sale
            ),
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK002",
                value_usd=30_000.0,
                code="S",
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_option_exercise_code_m_is_ignored(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=10),
                cik="CIK001",
                value_usd=50_000.0,
                code="M",  # option exercise
            ),
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK002",
                value_usd=50_000.0,
                code="A",  # award
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_mix_of_buy_and_sale_only_buys_count(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=10),
                cik="CIK001",
                value_usd=30_000.0,
                code="P",
            ),
            _buy(
                transaction_date=as_of - timedelta(days=8),
                cik="CIK001",
                value_usd=50_000.0,
                code="S",  # same CIK, sale — ignored
            ),
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK002",
                value_usd=25_000.0,
                code="P",
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        # Two distinct CIKs with P buys totalling $55k → long
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestIndirectOwnershipIgnored
# ---------------------------------------------------------------------------


class TestIndirectOwnershipIgnored:
    """Indirect ownership rows are filtered out."""

    def test_indirect_ownership_is_ignored(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=10),
                cik="CIK001",
                value_usd=30_000.0,
                direct="I",  # indirect
            ),
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK002",
                value_usd=30_000.0,
                direct="I",
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_direct_qualifies_indirect_ignored(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=10),
                cik="CIK001",
                value_usd=30_000.0,
                direct="D",
            ),
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK002",
                value_usd=100_000.0,
                direct="I",  # indirect — not counted
            ),
        ]
        # Only CIK001 qualifies; only 1 distinct buyer → flat
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestTenPercentOwnerOnlyIsFlat
# ---------------------------------------------------------------------------


class TestTenPercentOwnerOnlyIsFlat:
    """10% owner buys without officer or director role → score 0.0."""

    def test_pure_ten_percent_owner_excluded(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=10),
                cik="CIK001",
                value_usd=30_000.0,
                is_officer=False,
                is_director=False,
                is_ten_pct=True,
            ),
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK002",
                value_usd=30_000.0,
                is_officer=False,
                is_director=False,
                is_ten_pct=True,
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_ten_percent_owner_who_is_also_director_qualifies(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(
                transaction_date=as_of - timedelta(days=10),
                cik="CIK001",
                value_usd=30_000.0,
                is_officer=False,
                is_director=True,  # is also a director → qualifies
                is_ten_pct=True,
            ),
            _buy(
                transaction_date=as_of - timedelta(days=5),
                cik="CIK002",
                value_usd=25_000.0,
                is_officer=True,
                is_director=False,
                is_ten_pct=False,
            ),
        ]
        sig = InsiderBuyingSignal(insider_events={"AAPL": events})
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0


# ---------------------------------------------------------------------------
# TestCustomThresholds
# ---------------------------------------------------------------------------


class TestCustomThresholds:
    """min_buy_count=3, custom min_total_value_usd and lookback_days work correctly."""

    def test_three_buyer_threshold_requires_three(self):
        as_of = date(2024, 3, 1)
        # Only 2 distinct buyers; threshold requires 3
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=50_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK002", value_usd=50_000.0),
        ]
        sig = InsiderBuyingSignal(
            insider_events={"AAPL": events},
            min_buy_count=3,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_three_buyers_meet_threshold(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=30_000.0),
            _buy(transaction_date=as_of - timedelta(days=8), cik="CIK002", value_usd=30_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK003", value_usd=30_000.0),
        ]
        sig = InsiderBuyingSignal(
            insider_events={"AAPL": events},
            min_buy_count=3,
            min_total_value_usd=50_000.0,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 1.0

    def test_custom_lookback_days_respected(self):
        as_of = date(2024, 3, 1)
        events = [
            # These fall within 90d but outside custom 30d window
            _buy(transaction_date=as_of - timedelta(days=45), cik="CIK001", value_usd=30_000.0),
            _buy(transaction_date=as_of - timedelta(days=40), cik="CIK002", value_usd=30_000.0),
        ]
        sig = InsiderBuyingSignal(
            insider_events={"AAPL": events},
            lookback_days=30,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0

    def test_custom_value_threshold_respected(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=60_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK002", value_usd=60_000.0),
        ]
        sig = InsiderBuyingSignal(
            insider_events={"AAPL": events},
            min_total_value_usd=200_000.0,
        )
        result = sig.compute(_ctx(as_of))
        assert result.score == 0.0


# ---------------------------------------------------------------------------
# TestEmptyEventsList
# ---------------------------------------------------------------------------


class TestEmptyEventsList:
    """No events → score 0.0 with an informative note."""

    def test_missing_symbol_returns_flat(self):
        sig = InsiderBuyingSignal(insider_events={})
        result = sig.compute(_ctx(date(2024, 3, 1)))
        assert result.score == 0.0
        assert result.notes
        assert "no insider" in result.notes[0].lower()

    def test_empty_list_for_symbol_returns_flat(self):
        sig = InsiderBuyingSignal(insider_events={"AAPL": []})
        result = sig.compute(_ctx(date(2024, 3, 1)))
        assert result.score == 0.0

    def test_different_symbol_has_no_data(self):
        as_of = date(2024, 3, 1)
        events = [
            _buy(transaction_date=as_of - timedelta(days=10), cik="CIK001", value_usd=30_000.0),
            _buy(transaction_date=as_of - timedelta(days=5), cik="CIK002", value_usd=30_000.0),
        ]
        sig = InsiderBuyingSignal(insider_events={"MSFT": events})
        # Ask for AAPL, which has no data
        result = sig.compute(_ctx(as_of, symbol="AAPL"))
        assert result.score == 0.0
        assert "no insider" in result.notes[0].lower()


# ---------------------------------------------------------------------------
# TestSignalAttributes
# ---------------------------------------------------------------------------


class TestSignalAttributes:
    """name, version, and dataclass attributes required by Signal protocol."""

    def test_name(self):
        sig = InsiderBuyingSignal()
        assert sig.name == "insider_buying"

    def test_version(self):
        sig = InsiderBuyingSignal()
        assert sig.version == "0.1.0"

    def test_default_min_buy_count(self):
        sig = InsiderBuyingSignal()
        assert sig.min_buy_count == 2

    def test_default_min_total_value_usd(self):
        sig = InsiderBuyingSignal()
        assert sig.min_total_value_usd == pytest.approx(50_000.0)

    def test_default_lookback_days(self):
        sig = InsiderBuyingSignal()
        assert sig.lookback_days == 90

    def test_default_insider_events_is_empty_dict(self):
        sig = InsiderBuyingSignal()
        assert sig.insider_events == {}

    def test_insider_buy_dataclass_fields(self):
        ev = InsiderBuy(
            transaction_date=date(2024, 1, 15),
            cik="0000320193",
            transaction_shares=500,
            transaction_price=185.50,
            transaction_value_usd=92_750.0,
            transaction_code="P",
            direct_or_indirect_ownership="D",
            is_officer=True,
            is_director=False,
            is_ten_percent_owner=False,
        )
        assert ev.transaction_date == date(2024, 1, 15)
        assert ev.cik == "0000320193"
        assert ev.transaction_shares == 500
        assert ev.transaction_price == pytest.approx(185.50)
        assert ev.transaction_value_usd == pytest.approx(92_750.0)
        assert ev.transaction_code == "P"
        assert ev.direct_or_indirect_ownership == "D"
        assert ev.is_officer is True
        assert ev.is_director is False
        assert ev.is_ten_percent_owner is False
