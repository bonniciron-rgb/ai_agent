"""DB persistence helpers for external signals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from ai_agent.db.engine import get_session
from ai_agent.db.models import ExternalMessage, ExternalSignal
from ai_agent.external_signals.models import ParsedSignal, RawMessage


def get_latest_posted_at(channel: str) -> datetime | None:
    """Return the ``posted_at`` of the most-recent stored message for *channel*."""
    with get_session() as session:
        row = session.exec(
            select(ExternalMessage)
            .where(ExternalMessage.channel == channel)
            .order_by(ExternalMessage.posted_at.desc())  # type: ignore[arg-type]
            .limit(1)
        ).first()
        return row.posted_at if row else None


def message_exists(channel: str, message_id: int) -> bool:
    with get_session() as session:
        return (
            session.exec(
                select(ExternalMessage).where(
                    ExternalMessage.channel == channel,
                    ExternalMessage.message_id == message_id,
                )
            ).first()
            is not None
        )


def save_message(msg: RawMessage) -> int:
    """Persist *msg* and return the new DB row id."""
    with get_session() as session:
        row = ExternalMessage(
            channel=msg.channel,
            message_id=msg.message_id,
            posted_at=msg.posted_at,
            text=msg.text,
            processed=False,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id  # type: ignore[return-value]


def mark_processed(db_id: int) -> None:
    with get_session() as session:
        row = session.get(ExternalMessage, db_id)
        if row:
            row.processed = True
            session.add(row)
            session.commit()


def save_signal(
    signal: ParsedSignal, external_message_id: int, channel: str, posted_at: datetime
) -> None:
    with get_session() as session:
        row = ExternalSignal(
            external_message_id=external_message_id,
            channel=channel,
            posted_at=posted_at,
            symbol=signal.symbol,
            side=signal.side,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            target_price=signal.target_price,
            conviction=signal.conviction,
            notes=signal.notes,
        )
        session.add(row)
        session.commit()


def get_signals_for_symbol(symbol: str, days_back: int = 7) -> list[ExternalSignal]:
    """Return signals for *symbol* posted within the last *days_back* days."""
    since = datetime.now(UTC) - timedelta(days=days_back)
    with get_session() as session:
        rows = session.exec(
            select(ExternalSignal)
            .where(
                ExternalSignal.symbol == symbol.upper(),
                ExternalSignal.posted_at >= since,
            )
            .order_by(ExternalSignal.posted_at.desc())  # type: ignore[arg-type]
        ).all()
        return list(rows)
