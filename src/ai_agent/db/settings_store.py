"""DB-backed runtime settings (halt flag, etc.).

Used to toggle behaviour from Telegram without a redeploy: ``/halt`` writes
``trading_halted=1`` and the daily cron reads it before invoking the agent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import select

# Import the module (not the function) so monkeypatched ``get_session`` in tests
# is honoured even if this module is imported lazily inside a test body.
from ai_agent.db import engine as _engine
from ai_agent.db.models import Setting

HALT_KEY = "trading_halted"
TRUTHY = ("1", "true", "yes", "on")


def get_setting(key: str, default: str = "") -> str:
    with _engine.get_session() as session:
        row = session.exec(select(Setting).where(Setting.key == key)).first()
        return row.value if row else default


def set_setting(key: str, value: str, *, updated_by: str | None = None) -> None:
    with _engine.get_session() as session:
        row = session.exec(select(Setting).where(Setting.key == key)).first()
        if row is None:
            row = Setting(key=key, value=value, updated_by=updated_by)
        else:
            row.value = value
            row.updated_at = datetime.now(UTC)
            row.updated_by = updated_by
        session.add(row)
        session.commit()


def is_trading_halted() -> bool:
    """True if either the DB flag or the legacy ``TRADING_HALTED`` env var is set."""
    import os

    if os.environ.get("TRADING_HALTED", "").lower() in TRUTHY:
        return True
    return get_setting(HALT_KEY, "").lower() in TRUTHY


def set_trading_halted(halted: bool, *, updated_by: str | None = None) -> None:
    set_setting(HALT_KEY, "1" if halted else "0", updated_by=updated_by)
