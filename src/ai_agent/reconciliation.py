"""Nightly reconciliation logic.

Compares DB state (Position and Order tables) against what T212 actually holds.
Writes a ``Reconciliation`` row and sends a Telegram alert if drift is found.

Run directly::

    python -m ai_agent.reconciliation

Or via the convenience script::

    python scripts/reconcile.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import Session, select

from ai_agent.broker.t212_client import T212Client
from ai_agent.db.engine import get_engine, init_schema
from ai_agent.db.models import Order, OrderStatus, Position, Reconciliation
from ai_agent.settings import get_settings

logger = logging.getLogger(__name__)

# Thresholds for "material" drift
_POSITION_QTY_ABS_THRESHOLD = Decimal("1")  # shares
_POSITION_QTY_PCT_THRESHOLD = Decimal("0.001")  # 0.1 %


def _build_t212_client() -> T212Client:
    settings = get_settings()
    return T212Client(
        api_key=settings.t212_api_key.get_secret_value(),
        api_secret=settings.t212_api_secret.get_secret_value(),
        base_url=settings.t212_base_url,
    )


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def compare_positions(
    db_positions: list[Position],
    t212_positions: list,
) -> list[dict]:
    """Return drift records between DB and T212 open positions.

    A drift is defined as:
    - A symbol present in DB but not in T212 (or vice-versa).
    - A quantity difference > 1 share OR > 0.1%.
    """
    drifts: list[dict] = []

    db_map = {p.symbol: p for p in db_positions}
    t212_map: dict[str, object] = {}
    for pos in t212_positions:
        # T212 ticker format is e.g. "AAPL_US_EQ"; strip the suffix for matching.
        symbol = pos.ticker.split("_")[0] if "_" in pos.ticker else pos.ticker
        t212_map[symbol] = pos

    all_symbols = set(db_map.keys()) | set(t212_map.keys())

    for sym in sorted(all_symbols):
        db_pos = db_map.get(sym)
        t212_pos = t212_map.get(sym)

        if db_pos is None:
            drifts.append(
                {
                    "type": "position_missing_in_db",
                    "symbol": sym,
                    "t212_quantity": str(t212_pos.quantity),  # type: ignore[union-attr]
                }
            )
        elif t212_pos is None:
            drifts.append(
                {
                    "type": "position_missing_in_t212",
                    "symbol": sym,
                    "db_quantity": str(db_pos.quantity),
                }
            )
        else:
            db_qty = db_pos.quantity
            t212_qty = t212_pos.quantity  # type: ignore[union-attr]
            abs_diff = abs(db_qty - t212_qty)
            pct_diff = abs_diff / max(db_qty, t212_qty) if max(db_qty, t212_qty) else Decimal(0)
            if abs_diff > _POSITION_QTY_ABS_THRESHOLD or pct_diff > _POSITION_QTY_PCT_THRESHOLD:
                drifts.append(
                    {
                        "type": "position_quantity_mismatch",
                        "symbol": sym,
                        "db_quantity": str(db_qty),
                        "t212_quantity": str(t212_qty),
                        "abs_diff": str(abs_diff),
                        "pct_diff": f"{pct_diff:.4%}",
                    }
                )

    return drifts


def compare_orders(
    db_orders: list[Order],
    t212_orders: list,
) -> list[dict]:
    """Return drift records between today's DB submitted orders and T212 active orders.

    Drift cases:
    - DB order status = 'submitted' but T212 shows it as filled.
    - T212 has an active order today that doesn't exist in our DB.
    - DB shows 'submitted' for an order that T212 doesn't know about.
    """
    drifts: list[dict] = []

    # Index by broker order ID (string).
    t212_map = {str(o.id): o for o in t212_orders}
    db_map = {o.broker_order_id: o for o in db_orders if o.broker_order_id}

    for broker_id, t212_order in t212_map.items():
        db_order = db_map.get(broker_id)
        if db_order is None:
            drifts.append(
                {
                    "type": "order_in_t212_not_in_db",
                    "broker_order_id": broker_id,
                    "t212_status": t212_order.status,
                    "ticker": t212_order.ticker,
                }
            )
        elif db_order.status == OrderStatus.submitted and t212_order.status == "FILLED":
            drifts.append(
                {
                    "type": "order_filled_at_t212_but_db_submitted",
                    "broker_order_id": broker_id,
                    "symbol": db_order.symbol,
                    "db_status": str(db_order.status),
                    "t212_status": t212_order.status,
                }
            )

    for broker_id, db_order in db_map.items():
        if broker_id not in t212_map:
            drifts.append(
                {
                    "type": "order_submitted_in_db_not_found_at_t212",
                    "broker_order_id": broker_id,
                    "symbol": db_order.symbol,
                    "db_status": str(db_order.status),
                }
            )

    return drifts


# ---------------------------------------------------------------------------
# Telegram alert
# ---------------------------------------------------------------------------


def _send_telegram_alert(message: str) -> None:
    """Send a Telegram message via Bot API.  Logs and continues on any failure."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping alert")
        return
    try:
        import httpx

        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=15.0,
        )
        r.raise_for_status()
        logger.info("Telegram alert sent")
    except Exception as exc:
        logger.error("Failed to send Telegram alert: %s", exc)


# ---------------------------------------------------------------------------
# Main reconciliation logic
# ---------------------------------------------------------------------------


def run_reconciliation(
    t212_client: T212Client | None = None,
    engine=None,
) -> Reconciliation:
    """Execute one reconciliation run and persist the result.

    Parameters
    ----------
    t212_client:
        Optional pre-built client (useful for testing with a mock).
    engine:
        Optional SQLAlchemy engine (useful for testing with in-memory DB).

    Returns
    -------
    The ``Reconciliation`` row that was written to the DB.
    """
    if t212_client is None:
        if not get_settings().t212_api_key.get_secret_value():
            logger.warning("T212_API_KEY not set — skipping reconciliation")
            eng = engine or get_engine()
            recon_row = Reconciliation(
                run_at=datetime.now(UTC),
                status="skipped",
                position_drifts=0,
                order_drifts=0,
                details=json.dumps([{"type": "skipped", "message": "T212_API_KEY not set"}]),
            )
            with Session(eng) as session:
                session.add(recon_row)
                session.commit()
                session.refresh(recon_row)
            return recon_row
        t212_client = _build_t212_client()

    eng = engine or get_engine()
    run_at = datetime.now(UTC)
    status = "ok"
    position_drifts = 0
    order_drifts = 0
    details_list: list[dict] = []

    try:
        # --- Positions ---
        t212_positions = t212_client.get_positions()
        with Session(eng) as session:
            db_positions = list(session.exec(select(Position)).all())

        pos_drifts = compare_positions(db_positions, t212_positions)
        position_drifts = len(pos_drifts)
        details_list.extend(pos_drifts)

        # --- Orders ---
        # T212 get_orders() returns active (non-terminal) orders.
        # We compare against our DB's submitted orders from today.
        t212_orders = t212_client.get_orders()

        today_start = run_at.replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(eng) as session:
            db_today_orders = list(
                session.exec(
                    select(Order).where(
                        Order.status == OrderStatus.submitted,
                        Order.submitted_at >= today_start,
                    )
                ).all()
            )

        ord_drifts = compare_orders(db_today_orders, t212_orders)
        order_drifts = len(ord_drifts)
        details_list.extend(ord_drifts)

        if position_drifts > 0 or order_drifts > 0:
            status = "drift_detected"

    except Exception as exc:
        logger.exception("Reconciliation failed with error")
        status = "error"
        details_list.append({"type": "error", "message": str(exc)})

    # --- Persist ---
    recon_row = Reconciliation(
        run_at=run_at,
        status=status,
        position_drifts=position_drifts,
        order_drifts=order_drifts,
        details=json.dumps(details_list),
    )
    with Session(eng) as session:
        session.add(recon_row)
        session.commit()
        session.refresh(recon_row)

    logger.info(
        "Reconciliation complete: status=%s position_drifts=%d order_drifts=%d",
        status,
        position_drifts,
        order_drifts,
    )

    # --- Alert on drift or error ---
    if status == "drift_detected":
        msg = (
            f"⚠️ Reconciliation drift: {position_drifts} position mismatches, "
            f"{order_drifts} order mismatches. Check /reconciliation in dashboard."
        )
        _send_telegram_alert(msg)
    elif status == "error":
        err = next((d.get("message", "") for d in details_list if d.get("type") == "error"), "")
        _send_telegram_alert(f"⚠️ Reconciliation failed: {err}. Check /reconciliation in dashboard.")

    return recon_row


# ---------------------------------------------------------------------------
# Entry point (python -m ai_agent.reconciliation)
# ---------------------------------------------------------------------------


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Reconciliation job starting")
    init_schema()
    row = run_reconciliation()
    logger.info("Reconciliation job finished: status=%s", row.status)
    # Always exit 0 — drift is expected output, not a script failure.
    # The Telegram alert is the signal.
    return 0


if __name__ == "__main__":
    sys.exit(main())
