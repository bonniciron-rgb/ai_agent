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
