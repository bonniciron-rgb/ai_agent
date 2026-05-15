"""End-to-end smoke test for the daily loop.

Wires fakes for every external collaborator (T212, OHLCV, Anthropic,
Finnhub, Telegram) and asserts ``run()`` completes without exceptions
and produces the expected DB rows.

NOTE: All imports of `ai_agent.*` modules happen at module level (not inside
test functions). This is required so they're imported at pytest collection
time, BEFORE any fixture monkey-patches ``db.engine.get_session``. Lazy
imports inside test bodies would capture the patched lambda from the first
test and leak it across the whole module.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from ai_agent.agent.proposals import TradeProposal
from ai_agent.data.base import BarPoint, BarSeries
from ai_agent.data.finnhub_source import NewsItem
from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import Bar, DailyAnalysis, OrderSide, Proposal
from ai_agent.db.settings_store import set_trading_halted
from ai_agent.loop import daily_loop as dl
from ai_agent.loop.bar_store import ingest_bars
from ai_agent.loop.daily_loop import _build_toolbox, run
from ai_agent.loop.portfolio_snapshot import LivePortfolioSnapshot

# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)

    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)
    monkeypatch.delenv("TRADING_HALTED", raising=False)
    return engine


@pytest.fixture
def watchlist_path(tmp_path, monkeypatch):
    """Tiny watchlist with two symbols."""
    p = tmp_path / "watchlist.yaml"
    p.write_text(
        """\
entries:
  - symbol: AAPL
    sector: technology
  - symbol: MSFT
    sector: technology
"""
    )
    monkeypatch.setattr(dl, "WATCHLIST_PATH", p)
    return p


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeOhlcv:
    name = "fake-ohlcv"

    def get_daily(self, symbol, start, end):
        # Synthesise ~250 weekday bars of a gentle uptrend
        points = []
        d = end - timedelta(days=300)
        price = Decimal("100")
        while d <= end:
            if d.weekday() < 5:
                points.append(
                    BarPoint(
                        symbol=symbol,
                        trading_date=d,
                        open=price,
                        high=price + Decimal("2"),
                        low=price - Decimal("2"),
                        close=price + Decimal("1"),
                        volume=1_000_000,
                        source="fake",
                    )
                )
                price += Decimal("0.10")
            d += timedelta(days=1)
        return BarSeries(symbol=symbol, points=points)


class FakeT212:
    def get_cash(self):
        return SimpleNamespace(free=Decimal("50_000"), invested=Decimal("0"))

    def get_positions(self):
        return []


class FakeAnthropicClient:
    """Returns a single end_turn response so the agent loop terminates immediately."""

    def create_message(self, **kwargs):
        return SimpleNamespace(
            content=[],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


class FakeFinnhub:
    def company_news(self, symbol, *, start, end):
        return [
            NewsItem(
                symbol=symbol,
                headline="Apple beats earnings",
                summary="Q4 results topped estimates",
                source="reuters",
                published_at=datetime(2026, 5, 4, 12, 0, tzinfo=UTC),
            )
        ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_daily_loop_dry_run_no_proposals(watchlist_path) -> None:
    """Loop runs end-to-end with no proposals from the LLM."""
    run(
        dry_run=True,
        ohlcv_source=FakeOhlcv(),
        t212_client=FakeT212(),
        anthropic_client=FakeAnthropicClient(),
        finnhub_source=None,
        today=date(2026, 5, 5),
    )


def test_daily_loop_persists_passing_proposal(watchlist_path, _db, monkeypatch) -> None:
    """LLM returns one proposal; risk rails pass; DB row created."""
    proposal = TradeProposal(
        symbol="AAPL",
        side=OrderSide.buy,
        quantity=10,
        limit_price=Decimal("150"),
        stop_price=Decimal("143"),  # FakeOhlcv ATR≈4 → min stop = 142
        rationale="Strong uptrend, RSI not overbought.",
        confidence="medium",
    )

    def fake_run_agent(symbols, toolbox, **kwargs):
        return SimpleNamespace(
            proposals=[proposal],
            iterations=1,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            stop_reason="end_turn",
            # m16/m18 fields required by _save_proposals
            model="claude-opus-4-7",
            prompt_messages=[],
            response_text="",
        )

    async def _no_digest(*args, **kwargs):
        return None

    monkeypatch.setattr(dl, "run_agent", fake_run_agent)
    monkeypatch.setattr(dl, "_send_digest", _no_digest)

    run(
        dry_run=False,
        ohlcv_source=FakeOhlcv(),
        t212_client=FakeT212(),
        anthropic_client=None,
        finnhub_source=None,
        today=date(2026, 5, 5),
    )

    with Session(_db) as session:
        rows = session.exec(select(Proposal)).all()
        assert len(rows) == 1
        assert rows[0].symbol == "AAPL"
        analysis = session.exec(select(DailyAnalysis)).all()
        assert len(analysis) == 1
        a = analysis[0]
        assert a.as_of == date(2026, 5, 5)
        assert a.proposals_generated == 1
        assert a.proposals_passed_risk == 1
        assert a.proposals_blocked_risk == 0
        assert a.has_proposals


def test_daily_loop_persists_analysis_when_no_proposals(watchlist_path, _db, monkeypatch) -> None:
    """Agent returns nothing → still writes a DailyAnalysis row with the reasoning."""

    def fake_run_agent(symbols, toolbox, **kwargs):
        return SimpleNamespace(
            proposals=[],
            iterations=2,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            stop_reason="end_turn",
            model="claude-opus-4-7",
            prompt_messages=[],
            response_text="No qualifying setups today; broad indices extended, breadth weak.",
        )

    captured: dict = {}

    async def _capture_digest(saved, settings, *, no_proposal_text=None):
        captured["saved"] = saved
        captured["no_proposal_text"] = no_proposal_text

    monkeypatch.setattr(dl, "run_agent", fake_run_agent)
    monkeypatch.setattr(dl, "_send_digest", _capture_digest)

    run(
        dry_run=False,
        ohlcv_source=FakeOhlcv(),
        t212_client=FakeT212(),
        anthropic_client=None,
        finnhub_source=None,
        today=date(2026, 5, 6),
    )

    with Session(_db) as session:
        assert session.exec(select(Proposal)).all() == []
        analysis = session.exec(select(DailyAnalysis)).all()
        assert len(analysis) == 1
        a = analysis[0]
        assert a.as_of == date(2026, 5, 6)
        assert a.proposals_generated == 0
        assert a.proposals_passed_risk == 0
        assert not a.has_proposals
        assert "No qualifying setups today" in a.summary
        assert a.agent_iterations == 2

    # The 'no trade' Telegram message gets the reasoning blurb.
    assert captured["saved"] == []
    assert captured["no_proposal_text"] is not None
    assert "No qualifying setups today" in captured["no_proposal_text"]
    assert "/analysis" in captured["no_proposal_text"]


def test_daily_loop_halt_skips_run(watchlist_path) -> None:
    """If the halt flag is set, the loop returns early before touching T212."""
    set_trading_halted(True)

    class _ExplodingT212:
        def get_cash(self):
            raise AssertionError("should never be called when halted")

        def get_positions(self):
            raise AssertionError("should never be called when halted")

    run(
        dry_run=True,
        ohlcv_source=FakeOhlcv(),
        t212_client=_ExplodingT212(),
        anthropic_client=FakeAnthropicClient(),
        finnhub_source=None,
        today=date(2026, 5, 5),
    )


def test_daily_loop_ingests_bars(watchlist_path, _db) -> None:
    """Bar ingestion runs at the top of the loop and populates the Bar table."""
    run(
        dry_run=True,
        ohlcv_source=FakeOhlcv(),
        t212_client=FakeT212(),
        anthropic_client=FakeAnthropicClient(),
        finnhub_source=None,
        today=date(2026, 5, 5),
    )

    with Session(_db) as session:
        bars = session.exec(select(Bar)).all()
        assert len(bars) > 100
        symbols = {b.symbol for b in bars}
        assert symbols == {"AAPL", "MSFT"}


def test_daily_loop_features_use_ingested_bars(watchlist_path) -> None:
    """get_features in the toolbox returns real feature data from ingested bars."""
    ingest_bars(["AAPL"], source=FakeOhlcv(), today=date(2026, 5, 5))
    snap = LivePortfolioSnapshot(FakeT212(), reference_date=date(2026, 5, 5))
    toolbox = _build_toolbox(snap, today=date(2026, 5, 5))

    result = toolbox.dispatch("get_features", {"symbol": "AAPL"})
    assert "regime" in result
    assert "rsi_14" in result
    assert "error" not in result


def test_daily_loop_get_features_no_bars_returns_error(watchlist_path) -> None:
    """get_features with no bars in DB surfaces an error gracefully (no crash)."""
    snap = LivePortfolioSnapshot(FakeT212(), reference_date=date(2026, 5, 5))
    toolbox = _build_toolbox(snap, today=date(2026, 5, 5))

    result = toolbox.dispatch("get_features", {"symbol": "ZZZZ"})
    assert "error" in result


def test_daily_loop_get_news_no_finnhub_returns_empty(watchlist_path) -> None:
    """get_news returns empty list when Finnhub source is None (no API key)."""
    snap = LivePortfolioSnapshot(FakeT212(), reference_date=date(2026, 5, 5))
    toolbox = _build_toolbox(snap, finnhub_source=None, today=date(2026, 5, 5))

    result = toolbox.dispatch("get_news", {"symbol": "AAPL"})
    assert result == []


def test_daily_loop_get_news_uses_finnhub(watchlist_path) -> None:
    """get_news routes through the injected Finnhub source."""
    snap = LivePortfolioSnapshot(FakeT212(), reference_date=date(2026, 5, 5))
    toolbox = _build_toolbox(snap, finnhub_source=FakeFinnhub(), today=date(2026, 5, 5))

    result = toolbox.dispatch("get_news", {"symbol": "AAPL"})
    assert len(result) == 1
    assert "Apple beats earnings" in result[0]["headline"]
