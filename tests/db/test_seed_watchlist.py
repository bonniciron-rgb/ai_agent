"""Tests for the one-shot watchlist DB seeding script."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlmodel import Session

from ai_agent.db.engine import create_engine_from_url, init_schema
from ai_agent.db.watchlist_store import add_entry, list_entries

_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "seed_watchlist.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_watchlist", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def _write_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "watchlist.yaml"
    p.write_text(
        "entries:\n"
        "  - symbol: AAPL\n"
        "    sector: technology\n"
        "  - symbol: NEE\n"
        "    sector: utilities\n"
    )
    return p


def test_dry_run_adds_nothing(tmp_path):
    yaml_path = _write_yaml(tmp_path)
    mod = _load_script()

    rc = mod.main(["--path", str(yaml_path)])  # no --apply
    assert rc == 0
    assert list_entries() == []


def test_apply_adds_missing_symbols(tmp_path):
    yaml_path = _write_yaml(tmp_path)
    mod = _load_script()

    rc = mod.main(["--path", str(yaml_path), "--apply"])
    assert rc == 0
    symbols = {row.symbol for row in list_entries()}
    assert symbols == {"AAPL", "NEE"}


def test_apply_is_idempotent_and_only_adds_missing(tmp_path):
    yaml_path = _write_yaml(tmp_path)
    mod = _load_script()

    # AAPL already present; only NEE should be added.
    add_entry(symbol="AAPL", sector="technology")

    rc = mod.main(["--path", str(yaml_path), "--apply"])
    assert rc == 0
    symbols = sorted(row.symbol for row in list_entries())
    assert symbols == ["AAPL", "NEE"]  # no duplicate AAPL

    # Running again is a no-op.
    rc = mod.main(["--path", str(yaml_path), "--apply"])
    assert rc == 0
    assert sorted(row.symbol for row in list_entries()) == ["AAPL", "NEE"]
