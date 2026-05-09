"""DB-backed channel registry for external signal ingestion.

On the very first ingest run, if the signalchannel table is empty, the
YAML-configured channels are bootstrapped into the DB automatically.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_agent.db.engine import get_session
from ai_agent.db.models import SignalChannel


def bootstrap_from_yaml(handles: list[str]) -> None:
    """Insert YAML channels into DB if the table is empty."""
    with get_session() as session:
        existing = session.query(SignalChannel).first()
        if existing is not None:
            return
        for handle in handles:
            session.add(SignalChannel(handle=handle))
        session.commit()


def list_active_channels() -> list[str]:
    """Return handles of all non-paused channels."""
    with get_session() as session:
        rows = session.query(SignalChannel).filter(SignalChannel.paused == False).all()  # noqa: E712
        return [r.handle for r in rows]


def mark_channel_run(handle: str) -> None:
    """Update last_run_at timestamp for a channel after a successful ingest."""
    with get_session() as session:
        row = session.query(SignalChannel).filter(SignalChannel.handle == handle).first()
        if row:
            row.last_run_at = datetime.now(UTC)
            session.commit()


def add_channel(handle: str) -> SignalChannel:
    handle = handle.strip()
    if not handle.startswith("@"):
        handle = f"@{handle}"
    with get_session() as session:
        existing = session.query(SignalChannel).filter(SignalChannel.handle == handle).first()
        if existing:
            return existing
        row = SignalChannel(handle=handle)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def set_paused(channel_id: int, paused: bool) -> bool:
    with get_session() as session:
        row = session.query(SignalChannel).filter(SignalChannel.id == channel_id).first()
        if not row:
            return False
        row.paused = paused
        session.commit()
        return True


def delete_channel(channel_id: int) -> bool:
    with get_session() as session:
        row = session.query(SignalChannel).filter(SignalChannel.id == channel_id).first()
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True
