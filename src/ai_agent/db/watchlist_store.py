"""DB-backed watchlist store.

On first call, if the watchlistticker table is empty, the YAML-configured
entries are bootstrapped from config/watchlist.yaml automatically.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlmodel import select

import ai_agent.db.engine as _engine
from ai_agent.db.models import WatchlistTicker

_UNSET = object()


def bootstrap_from_yaml(yaml_path: str | Path) -> int:
    p = Path(yaml_path)
    if not p.exists():
        return 0
    with _engine.get_session() as session:
        existing = session.exec(select(WatchlistTicker)).first()
        if existing is not None:
            return 0
        raw = yaml.safe_load(p.read_text())
        entries = (raw or {}).get("entries", []) or []
        count = 0
        for entry in entries:
            symbol = entry.get("symbol", "")
            if not symbol:
                continue
            symbol = str(symbol).strip().upper()
            if not symbol:
                continue
            row = WatchlistTicker(
                symbol=symbol,
                sector=entry.get("sector"),
                notes=entry.get("notes"),
                tags_json=json.dumps(entry.get("tags", [])),
            )
            session.add(row)
            count += 1
        session.commit()
        return count


def list_entries() -> list[WatchlistTicker]:
    with _engine.get_session() as session:
        rows = session.exec(select(WatchlistTicker).order_by(WatchlistTicker.symbol)).all()
        return list(rows)


def list_active_symbols() -> list[str]:
    with _engine.get_session() as session:
        rows = session.exec(
            select(WatchlistTicker)
            .where(WatchlistTicker.paused == False)  # noqa: E712
            .order_by(WatchlistTicker.symbol)
        ).all()
        return [r.symbol for r in rows]


def add_entry(
    *,
    symbol: str,
    sector: str | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> WatchlistTicker:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol must not be empty")
    if len(symbol) > 16:
        raise ValueError("symbol must be 16 characters or fewer")
    if not re.match(r"^[A-Z0-9.\-]+$", symbol):
        raise ValueError(f"symbol contains invalid characters: {symbol!r}")
    with _engine.get_session() as session:
        existing = session.exec(
            select(WatchlistTicker).where(WatchlistTicker.symbol == symbol)
        ).first()
        if existing is not None:
            return existing
        row = WatchlistTicker(
            symbol=symbol,
            sector=sector,
            notes=notes,
            tags_json=json.dumps(tags or []),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def update_entry(
    entry_id: int,
    *,
    sector: str | None | object = _UNSET,
    notes: str | None | object = _UNSET,
    tags: list[str] | None | object = _UNSET,
    paused: bool | object = _UNSET,
) -> WatchlistTicker | None:
    with _engine.get_session() as session:
        row = session.exec(select(WatchlistTicker).where(WatchlistTicker.id == entry_id)).first()
        if row is None:
            return None
        if sector is not _UNSET:
            row.sector = sector  # type: ignore[assignment]
        if notes is not _UNSET:
            row.notes = notes  # type: ignore[assignment]
        if tags is not _UNSET:
            row.tags_json = json.dumps(tags or [])
        if paused is not _UNSET:
            row.paused = paused  # type: ignore[assignment]
        row.updated_at = datetime.now(UTC)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def delete_entry(entry_id: int) -> bool:
    with _engine.get_session() as session:
        row = session.exec(select(WatchlistTicker).where(WatchlistTicker.id == entry_id)).first()
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def to_watchlist():
    """Build the agent-facing Watchlist from the DB.

    Paused ("not followed") tickers are excluded — the agent only screens
    and proposes against actively-followed symbols. The watchlist editor
    reads the raw rows separately, so paused tickers stay visible there.
    """
    from ai_agent.watchlist import Watchlist, WatchlistEntry

    rows = list_entries()
    entries = [
        WatchlistEntry(
            symbol=row.symbol,
            sector=row.sector,
            notes=row.notes,
            tags=json.loads(row.tags_json or "[]"),
        )
        for row in rows
        if not row.paused
    ]
    return Watchlist(entries=entries)
