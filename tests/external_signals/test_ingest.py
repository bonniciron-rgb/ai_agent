"""Tests for the ingest orchestrator using fake reader + parser."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.external_signals.config import ExternalSignalsConfig
from ai_agent.external_signals.ingest import run_ingest
from ai_agent.external_signals.models import RawMessage
from ai_agent.external_signals.store import get_signals_for_symbol, message_exists

# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)

    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)

    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def _get_session(engine_arg=None) -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(eng_mod, "get_session", _get_session)
    return engine


# ---------------------------------------------------------------------------
# Fake reader and LLM client
# ---------------------------------------------------------------------------

CHANNEL = "@JdubTrades_Telegram"
NOW = datetime(2026, 5, 7, 10, 0, tzinfo=UTC)


class FakeReader:
    """Async-compatible fake channel reader."""

    def __init__(self, messages: list[RawMessage]) -> None:
        self._messages = messages

    async def fetch_messages(self, channel, since=None, limit=300):
        return self._messages


def _fake_llm(json_str: str):
    class _FakeMessages:
        def create(self, **kwargs):
            block = SimpleNamespace(text=json_str)
            return SimpleNamespace(content=[block])

    return SimpleNamespace(messages=_FakeMessages())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ingest_new_messages_stored() -> None:
    msgs = [RawMessage(message_id=1, channel=CHANNEL, posted_at=NOW, text="AAPL buy!")]
    reader = FakeReader(msgs)
    cfg = ExternalSignalsConfig(channels=[CHANNEL])

    run_ingest(cfg, reader=reader, llm_client=_fake_llm("[]"))

    assert message_exists(CHANNEL, 1)


def test_ingest_signals_extracted() -> None:
    msgs = [RawMessage(message_id=2, channel=CHANNEL, posted_at=NOW, text="AAPL buy here")]
    reader = FakeReader(msgs)
    cfg = ExternalSignalsConfig(channels=[CHANNEL])
    llm = _fake_llm('[{"symbol": "AAPL", "side": "buy", "conviction": "high"}]')

    results = run_ingest(cfg, reader=reader, llm_client=llm)

    assert results[0].signals_extracted == 1
    sigs = get_signals_for_symbol("AAPL", days_back=30)
    assert len(sigs) == 1
    assert sigs[0].conviction == "high"


def test_ingest_deduplicates_messages() -> None:
    msgs = [RawMessage(message_id=3, channel=CHANNEL, posted_at=NOW, text="test")]
    reader = FakeReader(msgs)
    cfg = ExternalSignalsConfig(channels=[CHANNEL])

    run_ingest(cfg, reader=reader, llm_client=_fake_llm("[]"))
    result2 = run_ingest(cfg, reader=reader, llm_client=_fake_llm("[]"))

    # Second run: 1 fetched, 0 new (already in DB)
    assert result2[0].fetched == 1
    assert result2[0].new == 0


def test_ingest_multiple_channels() -> None:
    ch2 = "@OtherChannel"
    cfg = ExternalSignalsConfig(channels=[CHANNEL, ch2])
    readers = {
        CHANNEL: FakeReader([RawMessage(message_id=10, channel=CHANNEL, posted_at=NOW, text="a")]),
        ch2: FakeReader([RawMessage(message_id=20, channel=ch2, posted_at=NOW, text="b")]),
    }

    class _MultiReader:
        async def fetch_messages(self, channel, since=None, limit=300):
            return readers[channel]._messages

    results = run_ingest(cfg, reader=_MultiReader(), llm_client=_fake_llm("[]"))

    assert len(results) == 2
    assert {r.channel for r in results} == {CHANNEL, ch2}
    assert all(r.new == 1 for r in results)


def test_ingest_reader_error_counted() -> None:
    class _BadReader:
        async def fetch_messages(self, channel, since=None, limit=300):
            raise RuntimeError("network failure")

    cfg = ExternalSignalsConfig(channels=[CHANNEL])
    results = run_ingest(cfg, reader=_BadReader(), llm_client=_fake_llm("[]"))

    assert results[0].errors == 1
    assert results[0].new == 0


def test_ingest_empty_channel() -> None:
    cfg = ExternalSignalsConfig(channels=[CHANNEL])
    results = run_ingest(cfg, reader=FakeReader([]), llm_client=_fake_llm("[]"))

    assert results[0].fetched == 0
    assert results[0].new == 0
    assert results[0].signals_extracted == 0


def test_ingest_result_counts() -> None:
    msgs = [
        RawMessage(message_id=100, channel=CHANNEL, posted_at=NOW, text="AAPL buy"),
        RawMessage(message_id=101, channel=CHANNEL, posted_at=NOW, text="general chat"),
    ]
    reader = FakeReader(msgs)
    cfg = ExternalSignalsConfig(channels=[CHANNEL])
    # Only first message has a signal
    llm = _fake_llm('[{"symbol": "AAPL", "side": "buy"}]')

    results = run_ingest(cfg, reader=reader, llm_client=llm)
    r = results[0]
    assert r.fetched == 2
    assert r.new == 2
    # parse_message is called for both, but signals come from LLM response.
    # Our fake always returns the same JSON for any input, so both produce 1 signal.
    assert r.signals_extracted == 2
