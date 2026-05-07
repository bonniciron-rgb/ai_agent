from pathlib import Path

import pytest

from ai_agent.watchlist import Watchlist, load_watchlist, merge_unique


def test_loads_example_watchlist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wl = load_watchlist(repo_root / "config" / "watchlist.example.yml")
    assert isinstance(wl, Watchlist)
    assert len(wl.symbols) > 0
    assert all(sym == sym.upper() for sym in wl.symbols)
    assert "SPY" in wl.symbols


def test_by_sector_groups() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wl = load_watchlist(repo_root / "config" / "watchlist.example.yml")
    by_sector = wl.by_sector()
    assert "technology" in by_sector
    assert any(e.symbol == "AAPL" for e in by_sector["technology"])


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_watchlist(tmp_path / "nope.yml")


def test_load_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.yml"
    p.write_text("")
    wl = load_watchlist(p)
    assert wl.entries == []


def test_load_invalid_root(tmp_path: Path) -> None:
    p = tmp_path / "bad.yml"
    p.write_text("- AAPL\n- MSFT\n")
    with pytest.raises(ValueError):
        load_watchlist(p)


def test_merge_unique_dedupes_and_uppercases() -> None:
    out = merge_unique(["aapl", "MSFT"], ["msft", "GOOGL", " AAPL "])
    assert out == ["AAPL", "MSFT", "GOOGL"]
