from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from ai_agent.bot.magic_link import issue_magic_token, magic_link


def _decode_part(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_secret_xyz")
    monkeypatch.delenv("SESSION_SECRET", raising=False)


def test_token_has_three_parts():
    tok = issue_magic_token("123")
    assert tok.count(".") == 2


def test_header_is_hs256_jwt():
    tok = issue_magic_token("123")
    header = json.loads(_decode_part(tok.split(".")[0]))
    assert header == {"alg": "HS256", "typ": "JWT"}


def test_payload_contains_uid_iat_exp():
    fixed_now = 1_700_000_000
    tok = issue_magic_token("6860533307", now=fixed_now, ttl_seconds=300)
    payload = json.loads(_decode_part(tok.split(".")[1]))
    assert payload == {
        "uid": "6860533307",
        "iat": fixed_now,
        "exp": fixed_now + 300,
    }


def test_uid_is_stringified():
    tok = issue_magic_token(42, now=1_700_000_000)
    payload = json.loads(_decode_part(tok.split(".")[1]))
    assert payload["uid"] == "42"


def test_signature_is_valid_hmac_sha256():
    tok = issue_magic_token("123", now=1_700_000_000)
    h, p, s = tok.split(".")
    body = f"{h}.{p}".encode()
    expected = hmac.new(b"test_secret_xyz", body, hashlib.sha256).digest()
    assert _decode_part(s) == expected


def test_session_secret_overrides_bot_token(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "override_secret")
    tok = issue_magic_token("123", now=1_700_000_000)
    h, p, s = tok.split(".")
    expected = hmac.new(b"override_secret", f"{h}.{p}".encode(), hashlib.sha256).digest()
    assert _decode_part(s) == expected


def test_default_ttl_is_five_minutes():
    before = int(time.time())
    tok = issue_magic_token("123")
    after = int(time.time())
    payload = json.loads(_decode_part(tok.split(".")[1]))
    assert payload["exp"] - payload["iat"] == 300
    assert before <= payload["iat"] <= after


def test_magic_link_strips_trailing_slash():
    link = magic_link("https://example.com/", "123")
    assert link.startswith("https://example.com/auth/magic?token=")
    assert "//auth/magic" not in link


def test_magic_link_includes_a_valid_token():
    link = magic_link("https://example.com", "123")
    token = link.split("token=", 1)[1]
    assert token.count(".") == 2


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(KeyError):
        issue_magic_token("123")
