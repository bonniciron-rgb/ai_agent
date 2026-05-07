"""Tests for BotHandlers using a fake DecisionStore and fake Telegram objects."""

from __future__ import annotations

import pytest

from ai_agent.bot.handlers import BotHandlers

# ---------------------------------------------------------------------------
# Fake store
# ---------------------------------------------------------------------------


class FakeStore:
    def __init__(self, symbols: dict[int, str] | None = None) -> None:
        self.decisions: list[tuple[int, str, str]] = []
        self._symbols = symbols or {1: "AAPL", 2: "MSFT"}

    def record_decision(self, proposal_id: int, action: str, decided_by: str) -> None:
        self.decisions.append((proposal_id, action, decided_by))

    def get_proposal_symbol(self, proposal_id: int) -> str | None:
        return self._symbols.get(proposal_id)


# ---------------------------------------------------------------------------
# Fake Telegram objects (no real SDK)
# ---------------------------------------------------------------------------


class FakeUser:
    id = 12345
    username = "trader_bob"


class FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.from_user = FakeUser()
        self._answered = False
        self._last_text: str | None = None
        self._markup_cleared = False

    async def answer(self) -> None:
        self._answered = True

    async def edit_message_text(self, text: str, **kwargs) -> None:
        self._last_text = text

    async def edit_message_reply_markup(self, **kwargs) -> None:
        self._markup_cleared = True


class FakeUpdate:
    def __init__(self, callback_data: str) -> None:
        self.callback_query = FakeQuery(callback_data)
        self.message = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_callback_approve_records_decision() -> None:
    store = FakeStore()
    handlers = BotHandlers(store=store)
    update = FakeUpdate("approve:1")

    # Patch isinstance check — make update pass as telegram.Update
    import ai_agent.bot.handlers as mod

    mod.__builtins__ if hasattr(mod, "__builtins__") else {}

    # We need to make isinstance(update, Update) return True.
    # Simplest: monkeypatch the telegram import inside handle_callback.
    import sys

    fake_telegram = type(sys)("telegram")
    fake_telegram.Update = type(update)
    sys.modules["telegram"] = fake_telegram

    try:
        await handlers.handle_callback(update, None)
    finally:
        sys.modules.pop("telegram", None)

    assert len(store.decisions) == 1
    assert store.decisions[0] == (1, "approve", "@trader_bob")


@pytest.mark.asyncio
async def test_handle_callback_bad_data_does_not_crash() -> None:
    store = FakeStore()
    handlers = BotHandlers(store=store)
    update = FakeUpdate("bad_data_no_colon")

    import sys

    fake_telegram = type(sys)("telegram")
    fake_telegram.Update = type(update)
    sys.modules["telegram"] = fake_telegram

    try:
        await handlers.handle_callback(update, None)
    finally:
        sys.modules.pop("telegram", None)

    # No decision recorded for invalid data
    assert store.decisions == []


@pytest.mark.asyncio
async def test_handle_callback_unknown_proposal_id() -> None:
    store = FakeStore(symbols={})  # no known proposals
    handlers = BotHandlers(store=store)
    update = FakeUpdate("reject:999")

    import sys

    fake_telegram = type(sys)("telegram")
    fake_telegram.Update = type(update)
    sys.modules["telegram"] = fake_telegram

    try:
        await handlers.handle_callback(update, None)
    finally:
        sys.modules.pop("telegram", None)

    # Decision still recorded even if symbol unknown
    assert any(d[0] == 999 and d[1] == "reject" for d in store.decisions)


# ---------------------------------------------------------------------------
# /halt, /resume, /status — DB-backed
# ---------------------------------------------------------------------------


class FakeMessage:
    def __init__(self) -> None:
        self.from_user = FakeUser()
        self._replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self._replies.append(text)


class FakeCommandUpdate:
    def __init__(self) -> None:
        self.callback_query = None
        self.message = FakeMessage()


@pytest.fixture
def _db(monkeypatch):
    """In-memory DB so /halt and /resume can write to the Setting table."""
    from sqlmodel import Session

    from ai_agent.db.engine import create_engine_from_url, init_schema

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
    monkeypatch.delenv("TRADING_HALTED", raising=False)
    return engine


@pytest.mark.asyncio
async def test_handle_halt_sets_db_flag(_db) -> None:
    from ai_agent.db.settings_store import is_trading_halted

    handlers = BotHandlers(store=FakeStore())
    update = FakeCommandUpdate()

    import sys

    fake_telegram = type(sys)("telegram")
    fake_telegram.Update = type(update)
    sys.modules["telegram"] = fake_telegram

    try:
        await handlers.handle_halt(update, None)
    finally:
        sys.modules.pop("telegram", None)

    assert is_trading_halted() is True
    assert any("halted" in r.lower() for r in update.message._replies)


@pytest.mark.asyncio
async def test_handle_resume_clears_db_flag(_db) -> None:
    from ai_agent.db.settings_store import is_trading_halted, set_trading_halted

    set_trading_halted(True)
    assert is_trading_halted() is True

    handlers = BotHandlers(store=FakeStore())
    update = FakeCommandUpdate()

    import sys

    fake_telegram = type(sys)("telegram")
    fake_telegram.Update = type(update)
    sys.modules["telegram"] = fake_telegram

    try:
        await handlers.handle_resume(update, None)
    finally:
        sys.modules.pop("telegram", None)

    assert is_trading_halted() is False
    assert any("resumed" in r.lower() for r in update.message._replies)


@pytest.mark.asyncio
async def test_handle_status_reports_running(_db) -> None:
    handlers = BotHandlers(store=FakeStore())
    update = FakeCommandUpdate()

    import sys

    fake_telegram = type(sys)("telegram")
    fake_telegram.Update = type(update)
    sys.modules["telegram"] = fake_telegram

    try:
        await handlers.handle_status(update, None)
    finally:
        sys.modules.pop("telegram", None)

    assert any("running" in r.lower() for r in update.message._replies)


@pytest.mark.asyncio
async def test_handle_status_reports_halted(_db) -> None:
    from ai_agent.db.settings_store import set_trading_halted

    set_trading_halted(True)

    handlers = BotHandlers(store=FakeStore())
    update = FakeCommandUpdate()

    import sys

    fake_telegram = type(sys)("telegram")
    fake_telegram.Update = type(update)
    sys.modules["telegram"] = fake_telegram

    try:
        await handlers.handle_status(update, None)
    finally:
        sys.modules.pop("telegram", None)

    assert any("halted" in r.lower() for r in update.message._replies)
