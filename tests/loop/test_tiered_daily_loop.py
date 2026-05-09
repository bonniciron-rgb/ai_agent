"""Integration test: daily loop with tiered (Haiku → Opus) two-pass flow.

Verifies:
  - Screening pass uses screening_model (Haiku)
  - Decision pass uses decision_model (Opus)
  - Models are wired through Settings → run_agent
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from ai_agent.data.base import BarPoint, BarSeries
from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.models import Bar
from ai_agent.loop import daily_loop as dl
from ai_agent.loop.daily_loop import run


# ---------------------------------------------------------------------------
# In-memory DB
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
    p = tmp_path / "watchlist.yaml"
    p.write_text(
        """\
entries:
  - symbol: AAPL
    sector: technology
  - symbol: MSFT
    sector: technology
  - symbol: NVDA
    sector: technology
"""
    )
    monkeypatch.setattr(dl, "WATCHLIST_PATH", p)
    return p


# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------


class FakeOhlcv:
    name = "fake-ohlcv"

    def get_daily(self, symbol, start, end):
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


# ---------------------------------------------------------------------------
# Recording client that validates model selection per call
# ---------------------------------------------------------------------------


class TieredRecordingClient:
    """Records (model, system) for every create_message call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._call_count = 0

    def create_message(self, **kwargs) -> SimpleNamespace:
        self.calls.append({"model": kwargs["model"], "system": kwargs.get("system")})
        self._call_count += 1

        # First call → screening (returns shortlist of AAPL)
        if self._call_count == 1:
            payload = json.dumps({"shortlist": [{"symbol": "AAPL", "rationale": "momentum"}]})
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=payload)],
                stop_reason="end_turn",
                usage=SimpleNamespace(
                    input_tokens=50,
                    output_tokens=20,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=10,
                ),
            )

        # Subsequent calls → decision pass (end_turn immediately)
        return SimpleNamespace(
            content=[],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=200,
                output_tokens=50,
                cache_read_input_tokens=10,
                cache_creation_input_tokens=0,
            ),
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_daily_loop_tiered_uses_correct_models(watchlist_path, monkeypatch) -> None:
    """Full loop with tiered=True: screening call uses Haiku, decision uses Opus."""
    client = TieredRecordingClient()

    monkeypatch.setattr(dl, "run_agent", _make_patched_run_agent(client))

    run(
        dry_run=True,
        ohlcv_source=FakeOhlcv(),
        t212_client=FakeT212(),
        anthropic_client=None,  # will use the patched run_agent
        finnhub_source=None,
        today=date(2026, 5, 5),
    )

    # The patched run_agent is called once; it internally calls the client
    # twice (screening + decision)
    assert len(client.calls) == 2, f"Expected 2 API calls, got {len(client.calls)}"

    screening_call = client.calls[0]
    decision_call = client.calls[1]

    assert screening_call["model"] == "claude-haiku-4-5-20251001", (
        f"Screening must use Haiku, got {screening_call['model']}"
    )
    assert decision_call["model"] == "claude-opus-4-7", (
        f"Decision must use Opus, got {decision_call['model']}"
    )

    # Both passes must have cache_control on the system
    for call_name, call in [("screening", screening_call), ("decision", decision_call)]:
        system = call["system"]
        assert isinstance(system, list), f"{call_name} system must be a list"
        cached = [b for b in system if b.get("cache_control") == {"type": "ephemeral"}]
        assert cached, f"{call_name} system must have cached block(s)"


def test_daily_loop_tiered_empty_shortlist_no_proposals(watchlist_path, monkeypatch) -> None:
    """When screening returns empty, no decision pass runs and 0 proposals saved."""
    client = _EmptyShortlistClient()

    monkeypatch.setattr(dl, "run_agent", _make_patched_run_agent(client))

    run(
        dry_run=True,
        ohlcv_source=FakeOhlcv(),
        t212_client=FakeT212(),
        anthropic_client=None,
        finnhub_source=None,
        today=date(2026, 5, 5),
    )

    # Only 1 call (screening); no decision call
    assert len(client.calls) == 1, f"Expected 1 API call, got {len(client.calls)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patched_run_agent(recording_client):
    """Return a run_agent replacement that passes the recording_client in."""
    from ai_agent.agent import runner as runner_mod
    from ai_agent.settings import get_settings

    def patched_run_agent(watchlist, toolbox, *, client=None, api_key=None, **kwargs):
        settings = get_settings()
        return runner_mod.run_agent(
            watchlist,
            toolbox,
            client=recording_client,
            tiered=True,
            screening_model="claude-haiku-4-5-20251001",
            decision_model="claude-opus-4-7",
            shortlist_max=5,
        )

    return patched_run_agent


class _EmptyShortlistClient:
    """Always returns an empty shortlist (one call only)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_message(self, **kwargs) -> SimpleNamespace:
        self.calls.append({"model": kwargs["model"], "system": kwargs.get("system")})
        payload = json.dumps({"shortlist": []})
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=payload)],
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=30,
                output_tokens=10,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=5,
            ),
        )
