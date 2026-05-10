"""DB-backed store for web push subscriptions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import select

from ai_agent.db import engine as _engine
from ai_agent.db.models import PushSubscription


def list_subscriptions() -> list[PushSubscription]:
    with _engine.get_session() as session:
        rows = session.exec(select(PushSubscription).order_by(PushSubscription.created_at)).all()
        return list(rows)


def add_subscription(
    *,
    endpoint: str,
    auth_key: str,
    p256dh_key: str,
    user_agent: str | None = None,
) -> PushSubscription:
    with _engine.get_session() as session:
        existing = session.exec(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        ).first()
        if existing:
            return existing
        row = PushSubscription(
            endpoint=endpoint,
            auth_key=auth_key,
            p256dh_key=p256dh_key,
            user_agent=user_agent,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def remove_subscription(endpoint: str) -> bool:
    with _engine.get_session() as session:
        row = session.exec(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        ).first()
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True


def mark_used(endpoint: str) -> None:
    with _engine.get_session() as session:
        row = session.exec(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        ).first()
        if row:
            row.last_used_at = datetime.now(UTC)
            session.commit()
