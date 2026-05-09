"""Telegram channel reader backed by Telethon (MTProto user-account client).

Authentication requires a one-time interactive login (run ``scripts/auth_telegram.py``
locally) which produces a *session string*.  That string is stored as the
``TELEGRAM_SESSION_STRING`` GitHub Secret and passed here at runtime — no
interactive prompt during CI.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from ai_agent.external_signals.models import RawMessage

logger = logging.getLogger(__name__)


class ChannelReaderProtocol(Protocol):
    """Interface for reading channel messages.  Injected in tests."""

    async def fetch_messages(
        self,
        channel: str,
        since: datetime | None = None,
        limit: int = 300,
    ) -> list[RawMessage]: ...


class TelegramChannelReader:
    """Read messages from public Telegram channels using a Telethon user session."""

    def __init__(self, api_id: int, api_hash: str, session_string: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._session_string = session_string

    async def fetch_messages(
        self,
        channel: str,
        since: datetime | None = None,
        limit: int = 300,
    ) -> list[RawMessage]:
        """Return up to *limit* messages from *channel*, stopping at *since*.

        Messages are returned newest-first.  Pass ``since`` to stop iterating
        once the cursor reaches that timestamp (avoids re-reading old history on
        subsequent runs).
        """
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:
            raise ImportError(
                "Install the 'signals' extra: pip install 'ai_agent[signals]'"
            ) from exc

        messages: list[RawMessage] = []
        since_utc = since.replace(tzinfo=UTC) if since and since.tzinfo is None else since

        async with TelegramClient(
            StringSession(self._session_string),
            self._api_id,
            self._api_hash,
        ) as client:
            async for msg in client.iter_messages(channel, limit=limit):
                if not msg.text:
                    continue
                posted = msg.date
                if since_utc is not None and posted <= since_utc:
                    break
                messages.append(
                    RawMessage(
                        message_id=msg.id,
                        channel=channel,
                        posted_at=posted,
                        text=msg.text,
                    )
                )

        logger.info("Fetched %d messages from %s", len(messages), channel)
        return messages
