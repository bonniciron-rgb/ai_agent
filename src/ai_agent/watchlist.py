from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class WatchlistEntry(BaseModel):
    symbol: str
    sector: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()


class Watchlist(BaseModel):
    entries: list[WatchlistEntry] = Field(default_factory=list)

    @property
    def symbols(self) -> list[str]:
        return [e.symbol for e in self.entries]

    def by_sector(self) -> dict[str, list[WatchlistEntry]]:
        out: dict[str, list[WatchlistEntry]] = {}
        for entry in self.entries:
            out.setdefault(entry.sector or "unknown", []).append(entry)
        return out


def load_watchlist(path: str | Path) -> Watchlist:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"watchlist file not found: {p}")
    raw = yaml.safe_load(p.read_text())
    if raw is None:
        return Watchlist(entries=[])
    if not isinstance(raw, dict) or "entries" not in raw:
        raise ValueError(f"watchlist {p} must be a mapping with an 'entries' key")
    return Watchlist.model_validate(raw)


def merge_unique(*lists: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for items in lists:
        for sym in items:
            s = sym.strip().upper()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out
