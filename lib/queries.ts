/**
 * Typed read-only queries against the Neon Postgres tables defined by
 * src/ai_agent/db/models.py (SQLModel uses lowercase table names).
 *
 * All queries are server-side only — never expose this module to the
 * client.  Pages that use it must be Server Components / route handlers.
 */

import { getSql } from "./db";

export type ProposalStatus =
  | "proposed"
  | "approved"
  | "rejected"
  | "deferred"
  | "expired"
  | "executed";

export type OrderSide = "buy" | "sell";

export type OrderStatus =
  | "pending"
  | "submitted"
  | "filled"
  | "partially_filled"
  | "cancelled"
  | "rejected"
  | "expired";

export type OrderType = "limit" | "stop" | "stop_limit" | "market";

export interface Proposal {
  id: number;
  created_at: Date;
  expires_at: Date;
  symbol: string;
  side: OrderSide;
  quantity: string;
  limit_price: string;
  stop_price: string | null;
  rationale: string;
  confidence: string;
  status: ProposalStatus;
  decided_at: Date | null;
  decided_by: string | null;
}

export interface Order {
  id: number;
  proposal_id: number | null;
  broker_order_id: string | null;
  symbol: string;
  side: OrderSide;
  order_type: OrderType;
  quantity: string;
  limit_price: string | null;
  stop_price: string | null;
  status: OrderStatus;
  submitted_at: Date | null;
  filled_at: Date | null;
  filled_quantity: string;
  avg_fill_price: string | null;
}

export interface DashboardStats {
  halted: boolean;
  proposals_today: number;
  proposals_pending: number;
  orders_today: number;
}

export async function isTradingHalted(): Promise<boolean> {
  const sql = getSql();
  const rows = await sql<{ value: string }[]>`
    SELECT value FROM setting WHERE key = 'trading_halted' LIMIT 1
  `;
  if (rows.length === 0) return false;
  const v = rows[0].value.toLowerCase();
  return v === "1" || v === "true" || v === "yes";
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const sql = getSql();
  const [halted, [proposalsToday], [proposalsPending], [ordersToday]] =
    await Promise.all([
      isTradingHalted(),
      sql<{ count: number }[]>`
        SELECT COUNT(*)::int AS count
        FROM proposal
        WHERE created_at >= CURRENT_DATE
      `,
      sql<{ count: number }[]>`
        SELECT COUNT(*)::int AS count
        FROM proposal
        WHERE status = 'proposed'
      `,
      sql<{ count: number }[]>`
        SELECT COUNT(*)::int AS count
        FROM "order"
        WHERE submitted_at >= CURRENT_DATE
      `,
    ]);

  return {
    halted,
    proposals_today: proposalsToday?.count ?? 0,
    proposals_pending: proposalsPending?.count ?? 0,
    orders_today: ordersToday?.count ?? 0,
  };
}

export async function listRecentProposals(limit = 50): Promise<Proposal[]> {
  const sql = getSql();
  return sql<Proposal[]>`
    SELECT
      id, created_at, expires_at, symbol, side, quantity::text AS quantity,
      limit_price::text AS limit_price, stop_price::text AS stop_price,
      rationale, confidence, status, decided_at, decided_by
    FROM proposal
    ORDER BY created_at DESC
    LIMIT ${limit}
  `;
}

export async function getProposal(id: number): Promise<Proposal | null> {
  const sql = getSql();
  const rows = await sql<Proposal[]>`
    SELECT
      id, created_at, expires_at, symbol, side, quantity::text AS quantity,
      limit_price::text AS limit_price, stop_price::text AS stop_price,
      rationale, confidence, status, decided_at, decided_by
    FROM proposal
    WHERE id = ${id}
    LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function getOrderForProposal(
  proposalId: number,
): Promise<Order | null> {
  const sql = getSql();
  const rows = await sql<Order[]>`
    SELECT
      id, proposal_id, broker_order_id, symbol, side, order_type,
      quantity::text AS quantity,
      limit_price::text AS limit_price,
      stop_price::text AS stop_price,
      status, submitted_at, filled_at,
      filled_quantity::text AS filled_quantity,
      avg_fill_price::text AS avg_fill_price
    FROM "order"
    WHERE proposal_id = ${proposalId}
    ORDER BY id DESC
    LIMIT 1
  `;
  return rows[0] ?? null;
}

export async function listRecentOrders(limit = 50): Promise<Order[]> {
  const sql = getSql();
  return sql<Order[]>`
    SELECT
      id, proposal_id, broker_order_id, symbol, side, order_type,
      quantity::text AS quantity,
      limit_price::text AS limit_price,
      stop_price::text AS stop_price,
      status, submitted_at, filled_at,
      filled_quantity::text AS filled_quantity,
      avg_fill_price::text AS avg_fill_price
    FROM "order"
    ORDER BY COALESCE(submitted_at, filled_at) DESC NULLS LAST, id DESC
    LIMIT ${limit}
  `;
}
