"""Tests for web push delivery."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.push_store import add_subscription, list_subscriptions
from ai_agent.digest.push_sender import PushPayload, send_to_all


@pytest.fixture(autouse=True)
def _db(monkeypatch):
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


_PAYLOAD = PushPayload(title="Test", body="Test body", url="/proposals")


def test_send_to_all_skips_when_vapid_unset(monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
    result = send_to_all(_PAYLOAD)
    assert result == 0
    assert list_subscriptions() == []


def test_send_to_all_skips_when_no_subscriptions(monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "fake_private")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "fake_public")
    result = send_to_all(_PAYLOAD)
    assert result == 0


def test_send_to_all_calls_webpush_for_each_sub(monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "fake_private")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "fake_public")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@example.com")

    add_subscription(
        endpoint="https://push.example.com/sub1", auth_key="auth1", p256dh_key="p256dh1"
    )
    add_subscription(
        endpoint="https://push.example.com/sub2", auth_key="auth2", p256dh_key="p256dh2"
    )

    mock_webpush = MagicMock()
    with patch("pywebpush.webpush", mock_webpush):
        result = send_to_all(_PAYLOAD)

    assert result == 2
    assert mock_webpush.call_count == 2

    calls_sub_info = [c.kwargs["subscription_info"] for c in mock_webpush.call_args_list]
    endpoints = {s["endpoint"] for s in calls_sub_info}
    assert endpoints == {"https://push.example.com/sub1", "https://push.example.com/sub2"}


def test_send_to_all_removes_410_subscriptions(monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "fake_private")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "fake_public")

    add_subscription(
        endpoint="https://push.example.com/gone", auth_key="auth3", p256dh_key="p256dh3"
    )

    from pywebpush import WebPushException

    mock_response = MagicMock()
    mock_response.status_code = 410
    exc = WebPushException("gone", response=mock_response)

    mock_webpush = MagicMock(side_effect=exc)
    with patch("pywebpush.webpush", mock_webpush):
        result = send_to_all(_PAYLOAD)

    assert result == 0
    assert list_subscriptions() == []


def test_send_to_all_keeps_subscription_on_other_errors(monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "fake_private")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "fake_public")

    add_subscription(
        endpoint="https://push.example.com/err", auth_key="auth4", p256dh_key="p256dh4"
    )

    from pywebpush import WebPushException

    mock_response = MagicMock()
    mock_response.status_code = 500
    exc = WebPushException("server error", response=mock_response)

    mock_webpush = MagicMock(side_effect=exc)
    with patch("pywebpush.webpush", mock_webpush):
        result = send_to_all(_PAYLOAD)

    assert result == 0
    assert len(list_subscriptions()) == 1
