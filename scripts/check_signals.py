"""Connectivity smoke test for every signal source.

Run via the ``signals-check`` GitHub Actions workflow (or locally with
real credentials in env vars).  Prints a PASS/FAIL line for each source
and exits non-zero if any required source fails.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def status(ok: bool, optional: bool = False) -> str:
    if ok:
        return f"{GREEN}PASS{RESET}"
    if optional:
        return f"{YELLOW}SKIP{RESET}"
    return f"{RED}FAIL{RESET}"


def line(name: str, ok: bool, detail: str, *, optional: bool = False) -> None:
    print(f"  [{status(ok, optional)}] {name:<22} {detail}")


def check_env() -> dict[str, bool]:
    """Return which env vars are set (non-empty)."""
    keys = [
        "ANTHROPIC_API_KEY",
        "FINNHUB_API_KEY",
        "FRED_API_KEY",
        "NEWSAPI_KEY",
        "DATABASE_URL",
        "T212_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "TELEGRAM_SESSION_STRING",
        "EDGAR_USER_AGENT",
    ]
    return {k: bool(os.environ.get(k, "").strip()) for k in keys}


def check_yfinance() -> tuple[bool, str]:
    try:
        from ai_agent.data.yfinance_source import YFinanceSource

        src = YFinanceSource()
        bars = src.get_daily("AAPL", start=date.today() - timedelta(days=10), end=date.today())
        if not bars.points:
            return False, "no bars returned"
        return True, f"{len(bars.points)} bars, last close=${bars.points[-1].close}"
    except Exception as exc:
        return False, str(exc)[:120]


def check_yahoo_chart() -> tuple[bool, str]:
    try:
        from ai_agent.data.yahoo_chart_source import YahooChartSource

        src = YahooChartSource()
        bars = src.get_daily("AAPL", start=date.today() - timedelta(days=10), end=date.today())
        if not bars.points:
            return False, "no bars returned"
        return True, f"{len(bars.points)} bars (fallback)"
    except Exception as exc:
        return False, str(exc)[:120]


def check_sec_edgar() -> tuple[bool, str]:
    try:
        from ai_agent.data.edgar_source import EdgarSource

        ua = os.environ.get("EDGAR_USER_AGENT", "ai_agent/0.1 (test@example.com)")
        src = EdgarSource(user_agent=ua)
        filings = src.recent_filings("AAPL", forms=("10-K",), limit=1)
        if not filings:
            return False, "no filings returned"
        return True, f"latest 10-K: {filings[0].filing_date.isoformat()}"
    except Exception as exc:
        return False, str(exc)[:120]


def check_finnhub() -> tuple[bool, str]:
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        return False, "FINNHUB_API_KEY not set"
    try:
        from ai_agent.data.finnhub_source import FinnhubSource

        src = FinnhubSource(api_key=key)
        items = src.company_news(
            "AAPL",
            start=date.today() - timedelta(days=3),
            end=date.today(),
        )
        return True, f"{len(items)} news items"
    except Exception as exc:
        return False, str(exc)[:120]


def check_fred() -> tuple[bool, str]:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        return False, "FRED_API_KEY not set"
    try:
        from ai_agent.data.fred_source import FredSource

        src = FredSource(api_key=key)
        # CPIAUCSL = US CPI; widely available
        observations = src.series(
            "CPIAUCSL",
            start=date.today() - timedelta(days=120),
            end=date.today(),
        )
        return True, f"{len(observations)} CPI observations"
    except Exception as exc:
        return False, str(exc)[:120]


def check_newsapi() -> tuple[bool, str]:
    key = os.environ.get("NEWSAPI_KEY", "").strip()
    if not key:
        return False, "NEWSAPI_KEY not set"
    try:
        import httpx

        r = httpx.get(
            "https://newsapi.org/v2/top-headlines",
            params={"category": "business", "country": "us", "pageSize": 1},
            headers={"X-Api-Key": key},
            timeout=10.0,
        )
        r.raise_for_status()
        total = r.json().get("totalResults", 0)
        return True, f"reachable, totalResults={total}"
    except Exception as exc:
        return False, str(exc)[:120]


def check_anthropic() -> tuple[bool, str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return False, "ANTHROPIC_API_KEY not set"
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say OK."}],
        )
        return True, f"haiku reply OK ({resp.usage.output_tokens} out tokens)"
    except Exception as exc:
        return False, str(exc)[:120]


def check_t212() -> tuple[bool, str]:
    key = os.environ.get("T212_API_KEY", "").strip()
    if not key:
        return False, "T212_API_KEY not set"
    try:
        from ai_agent.broker.t212_client import T212Client
        from ai_agent.settings import get_settings

        settings = get_settings()
        env_var = os.environ.get("T212_ENV", "(unset, defaulting to demo)")
        url = settings.t212_base_url
        key_preview = f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "(too short)"
        try:
            client = T212Client(api_key=key, base_url=url)
            cash = client.get_cash()
            return (
                True,
                f"env={env_var} url={url} key={key_preview} free={cash.free} {cash.currency}",
            )
        except Exception as inner:
            # Re-raise with diagnostic context
            raise RuntimeError(f"env={env_var} url={url} key={key_preview} → {inner}") from inner
    except Exception as exc:
        return False, str(exc)[:200]


def check_telegram_bot() -> tuple[bool, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return False, "TELEGRAM_BOT_TOKEN not set"
    try:
        import httpx

        r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10.0)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            return False, f"getMe returned ok=false: {data}"
        bot = data["result"]
        return True, f"@{bot['username']} ({bot['first_name']})"
    except Exception as exc:
        return False, str(exc)[:120]


def check_telegram_mtproto() -> tuple[bool, str]:
    api_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
    if not all([api_id, api_hash, session]):
        return False, "TELEGRAM_API_ID/HASH/SESSION_STRING not all set"
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        async def _check() -> str:
            client = TelegramClient(StringSession(session), int(api_id), api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                raise RuntimeError("session not authorized")
            me = await client.get_me()
            await client.disconnect()
            return f"logged in as @{me.username or me.first_name}"

        msg = asyncio.run(_check())
        return True, msg
    except Exception as exc:
        return False, str(exc)[:120]


def check_database() -> tuple[bool, str]:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return False, "DATABASE_URL not set"
    try:
        from sqlalchemy import inspect

        from ai_agent.db.engine import get_engine

        insp = inspect(get_engine())
        tables = insp.get_table_names()
        return True, f"{len(tables)} tables: {', '.join(sorted(tables)[:5])}..."
    except Exception as exc:
        return False, str(exc)[:120]


def main() -> int:
    print("=" * 70)
    print(" Signal Source Connectivity Check")
    print("=" * 70)

    env = check_env()

    print("\n[1/3] Environment variables:")
    for name, ok in env.items():
        line(name, ok, "set" if ok else "MISSING", optional=name in ("NEWSAPI_KEY",))

    print("\n[2/3] Free sources (no key required):")
    yf_ok, yf_msg = check_yfinance()
    line("yfinance", yf_ok, yf_msg)
    yahoo_ok, yahoo_msg = check_yahoo_chart()
    line("Yahoo chart (fallback)", yahoo_ok, yahoo_msg, optional=True)
    edgar_ok, edgar_msg = check_sec_edgar()
    line("SEC EDGAR", edgar_ok, edgar_msg)

    print("\n[3/3] Authenticated sources:")
    db_ok, db_msg = check_database()
    line("Neon Postgres", db_ok, db_msg)

    anth_ok, anth_msg = check_anthropic()
    line("Anthropic", anth_ok, anth_msg)

    finn_ok, finn_msg = check_finnhub()
    line("Finnhub", finn_ok, finn_msg)

    fred_ok, fred_msg = check_fred()
    line("FRED", fred_ok, fred_msg)

    news_ok, news_msg = check_newsapi()
    line("NewsAPI", news_ok, news_msg, optional=True)

    t212_ok, t212_msg = check_t212()
    line("Trading 212", t212_ok, t212_msg)

    bot_ok, bot_msg = check_telegram_bot()
    line("Telegram bot", bot_ok, bot_msg)

    tg_ok, tg_msg = check_telegram_mtproto()
    line("Telegram MTProto", tg_ok, tg_msg)

    print("\n" + "=" * 70)
    required = [yf_ok, edgar_ok, db_ok, anth_ok, finn_ok, fred_ok, t212_ok, bot_ok, tg_ok]
    passed = sum(1 for r in required if r)
    total = len(required)
    optional = [yahoo_ok, news_ok]
    optional_passed = sum(1 for r in optional if r)
    print(
        f" Required: {passed}/{total}  |  "
        f"Optional: {optional_passed}/2 (Yahoo chart fallback, NewsAPI)"
    )
    print("=" * 70)

    return 0 if all(required) else 1


if __name__ == "__main__":
    sys.exit(main())
