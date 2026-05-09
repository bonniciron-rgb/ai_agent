"""Tests for the DB-backed settings store + halt helpers."""

from __future__ import annotations

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.settings_store import (
    HALT_KEY,
    get_setting,
    is_trading_halted,
    set_setting,
    set_trading_halted,
)


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
    # Clear the env-var override that is_trading_halted respects
    monkeypatch.delenv("TRADING_HALTED", raising=False)
    return engine


def test_get_setting_returns_default_when_missing() -> None:
    assert get_setting("missing", "default-value") == "default-value"
    assert get_setting("missing") == ""


def test_set_and_get_setting() -> None:
    set_setting("foo", "bar")
    assert get_setting("foo") == "bar"


def test_set_setting_upserts() -> None:
    set_setting("foo", "first")
    set_setting("foo", "second")
    assert get_setting("foo") == "second"


def test_set_setting_records_user() -> None:
    from ai_agent.db.models import Setting

    set_setting("foo", "bar", updated_by="@alice")
    import ai_agent.db.engine as eng_mod

    with eng_mod.get_session() as session:
        from sqlmodel import select

        row = session.exec(select(Setting).where(Setting.key == "foo")).first()
        assert row is not None
        assert row.updated_by == "@alice"


def test_is_trading_halted_default_false() -> None:
    assert is_trading_halted() is False


def test_set_trading_halted_true() -> None:
    set_trading_halted(True)
    assert is_trading_halted() is True


def test_set_trading_halted_false_clears() -> None:
    set_trading_halted(True)
    set_trading_halted(False)
    assert is_trading_halted() is False


def test_halt_key_is_stable() -> None:
    set_trading_halted(True)
    assert get_setting(HALT_KEY) == "1"


def test_env_var_overrides_db(monkeypatch) -> None:
    """Legacy TRADING_HALTED env var still wins for backward compat."""
    monkeypatch.setenv("TRADING_HALTED", "1")
    set_trading_halted(False)
    assert is_trading_halted() is True


def test_set_trading_halted_records_user() -> None:
    from ai_agent.db.models import Setting

    set_trading_halted(True, updated_by="@bob")
    import ai_agent.db.engine as eng_mod

    with eng_mod.get_session() as session:
        from sqlmodel import select

        row = session.exec(select(Setting).where(Setting.key == HALT_KEY)).first()
        assert row is not None
        assert row.updated_by == "@bob"
