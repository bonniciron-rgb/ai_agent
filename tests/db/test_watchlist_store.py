"""Tests for the DB-backed watchlist store."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.watchlist_store import (
    add_entry,
    bootstrap_from_yaml,
    delete_entry,
    list_entries,
    to_watchlist,
    update_entry,
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


def _write_yaml(path: Path, entries: list[dict]) -> Path:
    import yaml

    yaml_path = path / "watchlist.yaml"
    yaml_path.write_text(yaml.dump({"entries": entries}))
    return yaml_path


def test_bootstrap_from_yaml_seeds_empty_table(tmp_path):
    yaml_path = _write_yaml(
        tmp_path,
        [
            {"symbol": "AAPL", "sector": "technology", "tags": ["ai"]},
            {"symbol": "MSFT", "sector": "technology"},
        ],
    )
    count = bootstrap_from_yaml(yaml_path)
    assert count == 2
    rows = list_entries()
    assert len(rows) == 2
    symbols = [r.symbol for r in rows]
    assert "AAPL" in symbols
    assert "MSFT" in symbols
    aapl = next(r for r in rows if r.symbol == "AAPL")
    assert json.loads(aapl.tags_json) == ["ai"]


def test_bootstrap_is_idempotent(tmp_path):
    yaml_path = _write_yaml(
        tmp_path,
        [
            {"symbol": "AAPL", "sector": "technology"},
            {"symbol": "MSFT", "sector": "technology"},
        ],
    )
    bootstrap_from_yaml(yaml_path)
    second = bootstrap_from_yaml(yaml_path)
    assert second == 0
    assert len(list_entries()) == 2


def test_bootstrap_skips_when_yaml_missing(tmp_path):
    result = bootstrap_from_yaml(tmp_path / "nonexistent.yaml")
    assert result == 0
    assert list_entries() == []


def test_add_entry_uppercases_and_validates():
    row = add_entry(symbol="aapl", sector="technology")
    assert row.symbol == "AAPL"

    with pytest.raises(ValueError):
        add_entry(symbol="AA PL")


def test_add_entry_idempotent_on_duplicate():
    first = add_entry(symbol="TSLA")
    second = add_entry(symbol="TSLA")
    assert second.id == first.id
    assert len(list_entries()) == 1


def test_update_entry_partial():
    import time

    row = add_entry(symbol="NVDA", sector="technology", notes="original")
    original_updated_at = row.updated_at
    time.sleep(0.01)

    updated = update_entry(row.id, paused=True)
    assert updated is not None
    assert updated.paused is True
    assert updated.sector == "technology"
    assert updated.notes == "original"
    assert updated.updated_at > original_updated_at


def test_update_entry_can_clear_field():
    row = add_entry(symbol="XOM", sector="energy")
    assert row.sector == "energy"

    updated = update_entry(row.id, sector=None)
    assert updated is not None
    assert updated.sector is None
    assert updated.symbol == "XOM"


def test_delete_entry():
    row = add_entry(symbol="JPM")
    assert delete_entry(row.id) is True
    assert delete_entry(row.id) is False


def test_to_watchlist_converts(tmp_path):
    yaml_path = _write_yaml(
        tmp_path,
        [
            {"symbol": "GOOGL", "sector": "communication_services", "tags": ["mega"]},
            {"symbol": "AMZN", "sector": "consumer_discretionary"},
        ],
    )
    bootstrap_from_yaml(yaml_path)
    watchlist = to_watchlist()
    assert len(watchlist.entries) == 2
    symbols = [e.symbol for e in watchlist.entries]
    assert "GOOGL" in symbols
    assert "AMZN" in symbols
    googl = next(e for e in watchlist.entries if e.symbol == "GOOGL")
    assert googl.tags == ["mega"]
    assert googl.sector == "communication_services"
