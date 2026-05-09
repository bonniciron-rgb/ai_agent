"""Orchestrator: fetch → parse → persist new messages from configured channels.

Called from the ``signals_ingest`` GitHub Actions cron (06:25 UTC Mon-Fri),
five minutes before the main daily trading loop.

Usage::

    python -m ai_agent.external_signals.ingest

Environment variables required::

    TELEGRAM_API_ID          — integer app ID from https://my.telegram.org
    TELEGRAM_API_HASH        — app hash from https://my.telegram.org
    TELEGRAM_SESSION_STRING  — string session from scripts/auth_telegram.py
    ANTHROPIC_API_KEY        — for the LLM parser
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ai_agent.db.engine import init_schema
from ai_agent.external_signals.client import ChannelReaderProtocol, TelegramChannelReader
from ai_agent.external_signals.config import ExternalSignalsConfig
from ai_agent.external_signals.models import RawMessage
from ai_agent.external_signals.parser import parse_message
from ai_agent.external_signals.store import (
    get_latest_posted_at,
    get_signals_for_symbol,  # re-exported for convenience
    mark_processed,
    message_exists,
    save_message,
    save_signal,
)

logger = logging.getLogger(__name__)

__all__ = ["IngestResult", "get_signals_for_symbol", "run_ingest"]


@dataclass
class IngestResult:
    channel: str
    fetched: int = 0
    new: int = 0
    signals_extracted: int = 0
    errors: int = 0
    skipped: list[str] = field(default_factory=list)


def run_ingest(
    config: ExternalSignalsConfig | None = None,
    *,
    reader: ChannelReaderProtocol | None = None,
    llm_client: Any | None = None,
    api_key: str | None = None,
) -> list[IngestResult]:
    """Fetch, parse, and persist new messages for all configured channels.

    Parameters
    ----------
    config:
        Loaded config; defaults to ``ExternalSignalsConfig.load()``.
    reader:
        Telegram reader implementation.  Defaults to ``TelegramChannelReader``
        built from env vars.  Inject a fake in tests.
    llm_client:
        ``anthropic.Anthropic`` instance.  Defaults to real SDK via env var.
    api_key:
        Anthropic API key fallback (uses ``ANTHROPIC_API_KEY`` env var if None).
    """
    if config is None:
        config = ExternalSignalsConfig.load()

    if reader is None:
        reader = _build_reader()

    results: list[IngestResult] = []
    for channel in config.channels:
        result = _ingest_channel(
            channel,
            config=config,
            reader=reader,
            llm_client=llm_client,
            api_key=api_key,
        )
        results.append(result)
        logger.info(
            "Channel %s — fetched=%d new=%d signals=%d errors=%d",
            channel,
            result.fetched,
            result.new,
            result.signals_extracted,
            result.errors,
        )
    return results


def _ingest_channel(
    channel: str,
    *,
    config: ExternalSignalsConfig,
    reader: ChannelReaderProtocol,
    llm_client: Any | None,
    api_key: str | None,
) -> IngestResult:
    result = IngestResult(channel=channel)

    # Determine cutoff: resume from last seen timestamp or full backfill
    last_seen = get_latest_posted_at(channel)
    if last_seen is None:
        since = datetime.now(UTC) - timedelta(days=config.backfill_days)
        logger.info("First run for %s — backfilling %d days", channel, config.backfill_days)
    else:
        since = last_seen
        logger.info("Resuming %s from %s", channel, since.isoformat())

    try:
        messages: list[RawMessage] = asyncio.run(
            reader.fetch_messages(channel, since=since, limit=500)
        )
    except Exception as exc:
        logger.error("Failed to fetch messages from %s: %s", channel, exc)
        result.errors += 1
        return result

    result.fetched = len(messages)

    for msg in messages:
        if message_exists(channel, msg.message_id):
            result.skipped.append(str(msg.message_id))
            continue

        try:
            db_id = save_message(msg)
        except Exception as exc:
            logger.warning("Could not save message %d: %s", msg.message_id, exc)
            result.errors += 1
            continue

        result.new += 1

        try:
            signals = parse_message(
                msg.text, model=config.parser_model, client=llm_client, api_key=api_key
            )
        except Exception as exc:
            logger.warning("Parser failed for message %d: %s", msg.message_id, exc)
            signals = []
            result.errors += 1

        for sig in signals:
            try:
                save_signal(sig, db_id, channel, msg.posted_at)
                result.signals_extracted += 1
            except Exception as exc:
                logger.warning("Could not save signal %r: %s", sig, exc)
                result.errors += 1

        mark_processed(db_id)

    return result


def _build_reader() -> TelegramChannelReader:
    api_id_str = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    session_string = os.environ.get("TELEGRAM_SESSION_STRING", "")

    if not all([api_id_str, api_hash, session_string]):
        raise RuntimeError(
            "TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_SESSION_STRING must all be set. "
            "Run scripts/auth_telegram.py once to generate the session string."
        )

    return TelegramChannelReader(
        api_id=int(api_id_str),
        api_hash=api_hash,
        session_string=session_string,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_schema()
    results = run_ingest()
    total_signals = sum(r.signals_extracted for r in results)
    print(f"Ingest complete — {total_signals} signals extracted across {len(results)} channel(s).")
    sys.exit(0)
