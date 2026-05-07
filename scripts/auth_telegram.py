#!/usr/bin/env python3
"""One-time interactive Telegram authentication.

Run this locally to generate a session string that can be stored as
``TELEGRAM_SESSION_STRING`` in GitHub Secrets.  The session string lets the
GitHub Actions cron authenticate without an interactive prompt.

Prerequisites
-------------
1. Visit https://my.telegram.org and create an app to get your API ID and hash.
2. Install the signals extra: pip install "ai_agent[signals]"

Usage
-----
    python scripts/auth_telegram.py

The script will ask for your phone number, send a Telegram code, and on
success print the session string.  Copy the entire printed string into your
GitHub Secret.
"""

import asyncio
import os
import sys


async def _auth() -> None:
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("Telethon not installed. Run: pip install 'ai_agent[signals]'")
        sys.exit(1)

    api_id_str = os.environ.get("TELEGRAM_API_ID") or input("Enter TELEGRAM_API_ID: ").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH") or input("Enter TELEGRAM_API_HASH: ").strip()

    try:
        api_id = int(api_id_str)
    except ValueError:
        print("TELEGRAM_API_ID must be an integer.")
        sys.exit(1)

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start()  # prompts for phone + OTP interactively
        session_string = client.session.save()

    print("\n" + "=" * 60)
    print("Session string (store as TELEGRAM_SESSION_STRING secret):")
    print("=" * 60)
    print(session_string)
    print("=" * 60)
    print("\nDo NOT share this string — it provides full account access.")


if __name__ == "__main__":
    asyncio.run(_auth())
