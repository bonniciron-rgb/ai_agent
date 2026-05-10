"""Tests for the DB-backed push subscription store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.push_store import (
    add_subscription,
    list_subscriptions,
    mark_used,
    remove_subscription,
)


@pytest.fixture(autouse=True)
def _db(monkeypatch, tmp_path):
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    init_schema(engine)

    import ai_agent.db.engine as eng_mod

    monkeypatch.setattr(eng_mod, "get_engine", lambda: engine)

    @contextmanager
    def _get_session(engine_arg=None) -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(eng_mod, "get_session", _get_session)
    return engine


def test_add_subscription_inserts_row():
    sub = add_subscription(
        endpoint="https://push.example.com/1",
        auth_key="authkey1",
        p256dh_key="p256dhkey1",
        user_agent="Mozilla/5.0",
    )
    assert sub.id is not None
    assert sub.endpoint == "https://push.example.com/1"
    assert sub.auth_key == "authkey1"
    assert sub.p256dh_key == "p256dhkey1"
    assert sub.user_agent == "Mozilla/5.0"
    assert sub.last_used_at is None


def test_add_subscription_idempotent():
    first = add_subscription(
        endpoint="https://push.example.com/2",
        auth_key="authkey2",
        p256dh_key="p256dhkey2",
    )
    second = add_subscription(
        endpoint="https://push.example.com/2",
        auth_key="different_key",
        p256dh_key="different_p256dh",
    )
    assert second.id == first.id
    assert len(list_subscriptions()) == 1


def test_list_subscriptions_ordered_by_created_at():
    add_subscription(endpoint="https://push.example.com/a", auth_key="k1", p256dh_key="p1")
    add_subscription(endpoint="https://push.example.com/b", auth_key="k2", p256dh_key="p2")
    add_subscription(endpoint="https://push.example.com/c", auth_key="k3", p256dh_key="p3")
    subs = list_subscriptions()
    assert len(subs) == 3
    endpoints = [s.endpoint for s in subs]
    assert "https://push.example.com/a" in endpoints
    assert "https://push.example.com/b" in endpoints
    assert "https://push.example.com/c" in endpoints


def test_remove_subscription_deletes_row():
    add_subscription(endpoint="https://push.example.com/d", auth_key="k4", p256dh_key="p4")
    result = remove_subscription("https://push.example.com/d")
    assert result is True
    assert list_subscriptions() == []


def test_remove_subscription_returns_false_when_missing():
    result = remove_subscription("https://push.example.com/nonexistent")
    assert result is False


def test_mark_used_updates_last_used_at():
    add_subscription(endpoint="https://push.example.com/e", auth_key="k5", p256dh_key="p5")
    mark_used("https://push.example.com/e")
    subs = list_subscriptions()
    assert subs[0].last_used_at is not None


def test_mark_used_noop_for_missing_endpoint():
    mark_used("https://push.example.com/nonexistent")
