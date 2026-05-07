"""Daily trading loop — entry point for the GitHub Actions cron job.

Called once per trading day at ~06:30 UTC (before US pre-market open).

Steps
-----
1. Init DB schema (idempotent, safe to run every day).
2. Load watchlist from ``watchlist.yaml``.
3. Build T212 client + LivePortfolioSnapshot.
4. Run the Claude agent to generate proposals.
5. Filter each proposal through RiskChecker.
6. Persist approved proposals to Postgres.
7. Send the Telegram digest.

Run locally::

    python -m ai_agent.loop.daily_loop

Environment variables (see Settings)::

    DATABASE_URL, ANTHROPIC_API_KEY, T212_API_KEY, TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID, WATCHLIST_PATH (default: watchlist.yaml)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ai_agent.agent.runner import run_agent
from ai_agent.agent.tools import Toolbox
from ai_agent.db.engine import get_session, init_schema
from ai_agent.db.models import OrderSide, Proposal, ProposalStatus
from ai_agent.loop.portfolio_snapshot import LivePortfolioSnapshot
from ai_agent.risk.rails import RiskChecker
from ai_agent.settings import get_settings
from ai_agent.watchlist import load_watchlist

logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path(os.environ.get("WATCHLIST_PATH", "watchlist.yaml"))
PROPOSAL_TTL_HOURS = 24


def _build_toolbox(t212_client, portfolio_snapshot: LivePortfolioSnapshot) -> Toolbox:
    """Wire live data sources into the agent Toolbox."""
    from ai_agent.data.features import FeaturePipeline

    pipeline = FeaturePipeline()

    def get_features(inputs: dict) -> dict:
        symbol = inputs["symbol"]
        try:
            snap = pipeline.snapshot(symbol)
            return snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)
        except Exception as exc:
            logger.warning("get_features failed for %s: %s", symbol, exc)
            return {"error": str(exc)}

    def get_news(inputs: dict) -> list[dict]:
        from ai_agent.data.news import fetch_finnhub_news

        symbol = inputs["symbol"]
        limit = int(inputs.get("limit", 5))
        try:
            return fetch_finnhub_news(symbol, limit=limit)
        except Exception as exc:
            logger.warning("get_news failed for %s: %s", symbol, exc)
            return []

    def get_portfolio(inputs: dict) -> dict:
        return {
            "nav": str(portfolio_snapshot.nav),
            "positions": {sym: str(val) for sym, val in portfolio_snapshot._positions.items()},
        }

    def propose_trade(inputs: dict):
        from decimal import Decimal

        from ai_agent.agent.proposals import TradeProposal
        from ai_agent.db.models import OrderSide

        return TradeProposal(
            symbol=inputs["symbol"],
            side=OrderSide(inputs["side"]),
            quantity=int(inputs["quantity"]),
            limit_price=Decimal(str(inputs["limit_price"])),
            stop_price=Decimal(str(inputs["stop_price"])) if inputs.get("stop_price") else None,
            rationale=inputs["rationale"],
            confidence=inputs["confidence"],
        )

    def get_external_signals(inputs: dict) -> list[dict]:
        from ai_agent.external_signals.store import get_signals_for_symbol

        symbol = inputs["symbol"]
        days_back = int(inputs.get("days_back", 7))
        try:
            rows = get_signals_for_symbol(symbol, days_back=days_back)
            return [
                {
                    "channel": r.channel,
                    "posted_at": r.posted_at.isoformat(),
                    "side": r.side,
                    "entry_price": float(r.entry_price) if r.entry_price else None,
                    "stop_price": float(r.stop_price) if r.stop_price else None,
                    "target_price": float(r.target_price) if r.target_price else None,
                    "conviction": r.conviction,
                    "notes": r.notes,
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning("get_external_signals failed for %s: %s", symbol, exc)
            return []

    return Toolbox(
        get_features=get_features,
        get_news=get_news,
        get_portfolio=get_portfolio,
        propose_trade=propose_trade,
        get_external_signals=get_external_signals,
    )


def _save_proposals(proposals, settings) -> list[Proposal]:
    """Persist TradeProposal objects to DB; return saved Proposal ORM rows."""
    saved: list[Proposal] = []
    expires_at = datetime.now(UTC) + timedelta(hours=PROPOSAL_TTL_HOURS)
    with get_session() as session:
        for p in proposals:
            row = Proposal(
                expires_at=expires_at,
                symbol=p.symbol,
                side=OrderSide(p.side),
                quantity=Decimal(p.quantity),
                limit_price=p.limit_price,
                stop_price=p.stop_price,
                rationale=p.rationale,
                confidence=p.confidence,
                status=ProposalStatus.proposed,
            )
            session.add(row)
            session.flush()  # populate row.id before commit
            saved.append(row)
        session.commit()
        # Refresh to get assigned IDs
        for row in saved:
            session.refresh(row)
    return saved


def _check_halt() -> bool:
    """Return True if the TRADING_HALTED env var is set (toggled by /halt Telegram command)."""
    return os.environ.get("TRADING_HALTED", "").lower() in ("1", "true", "yes")


async def _send_digest(saved_proposals: list[Proposal], settings) -> None:
    """Send the Telegram digest for saved proposals."""
    try:
        from telegram import Bot
    except ImportError:
        logger.warning("python-telegram-bot not installed — skipping Telegram digest")
        return

    token = settings.telegram_bot_token.get_secret_value()
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping digest")
        return

    from ai_agent.bot.digest import send_proposals

    bot = Bot(token=token)
    proposal_dicts = [
        {
            "id": p.id,
            "symbol": p.symbol,
            "side": str(p.side),
            "quantity": int(p.quantity),
            "limit_price": str(p.limit_price),
            "stop_price": str(p.stop_price) if p.stop_price else None,
            "rationale": p.rationale,
            "confidence": p.confidence,
        }
        for p in saved_proposals
    ]
    async with bot:
        await send_proposals(bot, chat_id, proposal_dicts)


def run(*, dry_run: bool = False) -> None:
    """Main entry point.  Set dry_run=True to skip DB writes and Telegram."""
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Daily loop starting (dry_run=%s)", dry_run)

    # 1. DB schema
    if not dry_run:
        init_schema()
        logger.info("DB schema initialised")

    # 2. Watchlist
    if not WATCHLIST_PATH.exists():
        logger.error("Watchlist not found: %s", WATCHLIST_PATH)
        sys.exit(1)
    watchlist = load_watchlist(WATCHLIST_PATH)
    if not watchlist.symbols:
        logger.warning("Watchlist is empty — nothing to analyse")
        return
    logger.info("Watchlist: %s", watchlist.symbols)

    # 3. Halt check
    if _check_halt():
        logger.warning("Trading is halted — skipping agent run")
        return

    # 4. T212 + portfolio snapshot
    from ai_agent.broker.t212_client import T212Client

    t212 = T212Client(
        api_key=settings.t212_api_key.get_secret_value(),
        base_url=settings.t212_base_url,
    )
    sector_map = {e.symbol: e.sector for e in watchlist.entries if e.sector}
    portfolio = LivePortfolioSnapshot(t212, watchlist_sectors=sector_map)
    logger.info("Portfolio NAV: %s", portfolio.nav)

    # 5. Agent
    toolbox = _build_toolbox(t212, portfolio)
    result = run_agent(
        watchlist.symbols,
        toolbox,
        api_key=settings.anthropic_api_key.get_secret_value(),
    )
    logger.info(
        "Agent finished: %d proposals, %d iterations",
        len(result.proposals),
        result.iterations,
    )

    # 6. Risk filter
    checker = RiskChecker(portfolio=portfolio)
    passing: list = []
    for proposal in result.proposals:
        rail = checker.check(
            symbol=proposal.symbol,
            side=str(proposal.side),
            quantity=proposal.quantity,
            limit_price=proposal.limit_price,
            stop_price=proposal.stop_price,
        )
        if rail.allowed:
            passing.append(proposal)
            if checker.warnings:
                logger.info("Risk warnings for %s: %s", proposal.symbol, checker.warnings)
        else:
            logger.info("Proposal %s blocked by risk rail: %s", proposal.symbol, rail.reason)

    logger.info("%d/%d proposals passed risk rails", len(passing), len(result.proposals))

    # 7. Persist + digest
    if dry_run:
        logger.info("[dry_run] Would save %d proposals and send digest", len(passing))
        for p in passing:
            logger.info("  %s %s x%d @ %s", p.side, p.symbol, p.quantity, p.limit_price)
        return

    saved = _save_proposals(passing, settings)
    logger.info("Saved %d proposals to DB", len(saved))

    asyncio.run(_send_digest(saved, settings))
    logger.info("Telegram digest sent")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
