"""Daily trading loop — entry point for the GitHub Actions cron job.

Called once per trading day at ~06:30 UTC (before US pre-market open).

Steps
-----
1. Init DB schema (idempotent).
2. Load DB-backed watchlist (bootstrapped from yaml).
3. Check the DB-backed halt flag (toggled by ``/halt`` Telegram command).
4. Ingest fresh OHLCV bars for every watchlist symbol (yfinance + Stooq fallback).
5. Build T212 client + LivePortfolioSnapshot.
6. Run the Claude agent with a Toolbox wired to live data.
7. Filter each proposal through RiskChecker (5 rails).
8. Persist passing proposals to Postgres and send the Telegram digest.

Run locally::

    python -m ai_agent.loop.daily_loop --dry-run
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlmodel import select

from ai_agent.agent.runner import AgentResult, run_agent
from ai_agent.agent.tools import Toolbox
from ai_agent.db.engine import get_session, init_schema
from ai_agent.db.models import (
    DailyAnalysis,
    OrderSide,
    Proposal,
    ProposalReasoning,
    ProposalStatus,
    ShadowPosition,
)
from ai_agent.db.settings_store import is_trading_halted
from ai_agent.loop.bar_store import bars_from_db, ingest_bars
from ai_agent.loop.portfolio_snapshot import LivePortfolioSnapshot
from ai_agent.risk.rails import RiskChecker
from ai_agent.settings import get_settings
from ai_agent.watchlist import load_watchlist_from_db

logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path(os.environ.get("WATCHLIST_PATH", "config/watchlist.yaml"))
PROPOSAL_TTL_HOURS = 24
BAR_DAYS_BACK = 300  # ~250 trading days, enough for SMA-200 + warmup
NEWS_DAYS_BACK = 7


# ---------------------------------------------------------------------------
# Live data sources
# ---------------------------------------------------------------------------


def _build_default_ohlcv_source():
    """Construct the default OHLCV source chain: yfinance → Stooq fallback."""
    from ai_agent.data.registry import OhlcvChain
    from ai_agent.data.stooq_source import StooqSource
    from ai_agent.data.yfinance_source import YFinanceSource

    return OhlcvChain([YFinanceSource(), StooqSource()])


def _build_finnhub_source(api_key: str):
    """Return a FinnhubSource if the API key is set, else None."""
    if not api_key:
        return None
    from ai_agent.data.finnhub_source import FinnhubSource

    return FinnhubSource(api_key=api_key)


def _build_toolbox(
    portfolio_snapshot: LivePortfolioSnapshot,
    *,
    finnhub_source: Any | None = None,
    today: date | None = None,
) -> Toolbox:
    """Wire live data sources into the agent Toolbox."""
    from ai_agent.features.pipeline import compute_features

    ref_date = today or datetime.now(UTC).date()

    def get_features(inputs: dict) -> dict:
        symbol = inputs["symbol"]
        try:
            series = bars_from_db(symbol, days_back=BAR_DAYS_BACK, ref_date=ref_date)
            if not series.points:
                return {"error": f"no bars in DB for {symbol}"}
            snap = compute_features(series)
            return snap.model_dump(mode="json")
        except Exception as exc:
            logger.warning("get_features failed for %s: %s", symbol, exc)
            return {"error": str(exc)}

    def get_news(inputs: dict) -> list[dict]:
        if finnhub_source is None:
            return []
        symbol = inputs["symbol"]
        limit = int(inputs.get("limit", 5))
        try:
            items = finnhub_source.company_news(
                symbol,
                start=ref_date - timedelta(days=NEWS_DAYS_BACK),
                end=ref_date,
            )
            return [item.model_dump(mode="json") for item in items[:limit]]
        except Exception as exc:
            logger.warning("get_news failed for %s: %s", symbol, exc)
            return []

    def get_portfolio(inputs: dict) -> dict:
        return {
            "nav": str(portfolio_snapshot.nav),
            "positions": {sym: str(val) for sym, val in portfolio_snapshot._positions.items()},
        }

    def propose_trade(inputs: dict):
        from ai_agent.agent.proposals import TradeProposal

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


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _build_prompt_text(result: AgentResult) -> str:
    """Serialise the full conversation to a plain-text audit trail."""
    import json

    model = getattr(result, "model", "unknown")
    prompt_messages = getattr(result, "prompt_messages", [])
    parts: list[str] = [f"[MODEL: {model}]", ""]
    for msg in prompt_messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(f"[{role}]\n{content}")
        elif isinstance(content, list):
            for block in content:
                if hasattr(block, "type"):
                    if block.type == "text":
                        parts.append(f"[{role}]\n{block.text}")
                    elif block.type == "tool_use":
                        parts.append(
                            f"[{role}/tool_use:{block.name}]\n"
                            + json.dumps(block.input, default=str)
                        )
                    elif block.type == "tool_result":
                        parts.append(f"[{role}/tool_result]\n{block.content}")
                elif isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append(f"[{role}]\n{block.get('text', '')}")
                    elif btype == "tool_result":
                        parts.append(
                            f"[{role}/tool_result:{block.get('tool_use_id', '')}]\n"
                            + str(block.get("content", ""))
                        )
    return "\n\n".join(parts)


def _save_proposals(proposals, agent_result: AgentResult | None = None) -> list[Proposal]:
    """Persist TradeProposal objects to DB; return saved Proposal ORM rows.

    Also writes ProposalReasoning and ShadowPosition rows for every proposal.
    """
    saved: list[Proposal] = []
    expires_at = datetime.now(UTC) + timedelta(hours=PROPOSAL_TTL_HOURS)

    # Build reasoning audit text once (use getattr so SimpleNamespace fakes in tests still work)
    prompt_text = _build_prompt_text(agent_result) if agent_result else ""
    response_text = getattr(agent_result, "response_text", "") if agent_result else ""
    model = getattr(agent_result, "model", "unknown") if agent_result else "unknown"
    input_tokens = getattr(agent_result, "input_tokens", 0) if agent_result else 0
    output_tokens = getattr(agent_result, "output_tokens", 0) if agent_result else 0

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
            session.flush()

            # Write reasoning audit row
            reasoning = ProposalReasoning(
                proposal_id=row.id,
                prompt_text=prompt_text,
                response_text=response_text,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            session.add(reasoning)

            # Write shadow position row (decision=None until user acts)
            shadow = ShadowPosition(
                proposal_id=row.id,
                symbol=p.symbol,
                side=str(p.side),
                decision=None,
                opened_price=float(p.limit_price),
            )
            session.add(shadow)

            saved.append(row)
        session.commit()
        for row in saved:
            session.refresh(row)
    return saved


def _save_daily_analysis(
    *,
    as_of: date,
    symbols: list[str],
    agent_result: AgentResult,
    passed: int,
    blocked: int,
) -> DailyAnalysis:
    """Upsert the DailyAnalysis audit row for *as_of* (written every live run)."""
    summary = (getattr(agent_result, "response_text", "") or "")[:8000]
    model = getattr(agent_result, "model", "unknown") or "unknown"
    generated = len(getattr(agent_result, "proposals", []) or [])
    iterations = getattr(agent_result, "iterations", 0) or 0

    with get_session() as session:
        row = session.exec(select(DailyAnalysis).where(DailyAnalysis.as_of == as_of)).first()
        if row is None:
            row = DailyAnalysis(as_of=as_of)
            session.add(row)
        row.symbols_considered_json = json.dumps(list(symbols))
        row.proposals_generated = generated
        row.proposals_passed_risk = passed
        row.proposals_blocked_risk = blocked
        row.agent_iterations = iterations
        row.summary = summary
        row.model = model
        session.commit()
        session.refresh(row)
        return row


def _no_proposal_summary(analysis: DailyAnalysis) -> str:
    """Short human line for the 'no trade today' Telegram message."""
    head = analysis.summary.strip().splitlines()
    first = head[0][:400] if head else "No qualifying setups found."
    return (
        f"{first}\n\n({analysis.proposals_generated} ideas considered, "
        f"{analysis.proposals_blocked_risk} blocked by risk rails — "
        "full detail on the /analysis page.)"
    )


async def _send_digest(
    saved_proposals: list[Proposal], settings, *, no_proposal_text: str | None = None
) -> None:
    """Send the Telegram digest for saved proposals (or the 'no trade' note)."""
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
        await send_proposals(bot, chat_id, proposal_dicts, no_proposal_text=no_proposal_text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    *,
    dry_run: bool = False,
    ohlcv_source: Any | None = None,
    finnhub_source: Any | None = None,
    t212_client: Any | None = None,
    anthropic_client: Any | None = None,
    today: date | None = None,
) -> None:
    """Main entry point.

    All external collaborators can be injected for the smoke test; in production
    the cron just calls ``run(dry_run=False)`` and everything is built from env vars.
    """
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Daily loop starting (dry_run=%s)", dry_run)

    # 1. DB schema
    init_schema()

    # 2. Watchlist
    watchlist = load_watchlist_from_db(yaml_fallback_path=WATCHLIST_PATH)
    if not watchlist.symbols:
        logger.warning("Watchlist is empty — nothing to analyse")
        return
    logger.info("Watchlist: %s", watchlist.symbols)

    # 3. Halt check
    if is_trading_halted():
        logger.warning("Trading is halted — skipping agent run")
        return

    # 4. Bar ingestion (idempotent — duplicates are skipped)
    if ohlcv_source is None:
        ohlcv_source = _build_default_ohlcv_source()
    inserted = ingest_bars(
        watchlist.symbols,
        source=ohlcv_source,
        days_back=BAR_DAYS_BACK,
        today=today,
    )
    logger.info("Ingested %d new bars", inserted)

    # 5. T212 + portfolio snapshot
    if t212_client is None:
        from ai_agent.broker.t212_client import T212Client

        t212_client = T212Client(
            api_key=settings.t212_api_key.get_secret_value(),
            base_url=settings.t212_base_url,
        )
    sector_map = {e.symbol: e.sector for e in watchlist.entries if e.sector}
    portfolio = LivePortfolioSnapshot(
        t212_client,
        watchlist_sectors=sector_map,
        reference_date=today,
    )
    logger.info("Portfolio NAV: %s", portfolio.nav)

    # 6. Agent
    if finnhub_source is None:
        finnhub_source = _build_finnhub_source(settings.finnhub_api_key.get_secret_value())
    toolbox = _build_toolbox(
        portfolio,
        finnhub_source=finnhub_source,
        today=today,
    )
    result = run_agent(
        watchlist.symbols,
        toolbox,
        client=anthropic_client,
        api_key=settings.anthropic_api_key.get_secret_value() or None,
        tiered=settings.llm_tiered,
        screening_model=settings.llm_screening_model,
        decision_model=settings.llm_decision_model,
        shortlist_max=settings.llm_shortlist_max,
    )
    logger.info(
        "Agent finished: %d proposals, %d iterations",
        len(result.proposals),
        result.iterations,
    )

    # 7. Risk filter
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

    blocked = len(result.proposals) - len(passing)
    as_of = today or datetime.now(UTC).date()
    logger.info("%d/%d proposals passed risk rails", len(passing), len(result.proposals))

    # 8. Persist + digest
    if dry_run:
        logger.info("[dry_run] Would save %d proposals and send digest", len(passing))
        for p in passing:
            logger.info("  %s %s x%d @ %s", p.side, p.symbol, p.quantity, p.limit_price)
        # Still write reasoning + shadow rows even in dry-run so we can audit
        if passing:
            _save_proposals(passing, agent_result=result)
            logger.info("[dry_run] Wrote reasoning + shadow rows for %d proposals", len(passing))
        return

    analysis = _save_daily_analysis(
        as_of=as_of,
        symbols=watchlist.symbols,
        agent_result=result,
        passed=len(passing),
        blocked=blocked,
    )
    logger.info(
        "Saved DailyAnalysis for %s (generated=%d passed=%d)",
        as_of,
        analysis.proposals_generated,
        analysis.proposals_passed_risk,
    )

    saved = _save_proposals(passing, agent_result=result)
    logger.info("Saved %d proposals to DB", len(saved))

    no_proposal_text = _no_proposal_summary(analysis) if not saved else None
    asyncio.run(_send_digest(saved, settings, no_proposal_text=no_proposal_text))
    logger.info("Telegram digest sent")


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
