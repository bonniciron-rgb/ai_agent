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

export interface ProposalFilters {
  status?: ProposalStatus;
  symbol?: string;
  from?: string; // YYYY-MM-DD
}

/** Filtered proposal list (used by /proposals with URL params). */
export async function listProposalsFiltered(
  filters: ProposalFilters,
  limit = 100,
): Promise<Proposal[]> {
  const sql = getSql();
  const status = filters.status ?? null;
  const symbol = filters.symbol ? filters.symbol.toUpperCase() : null;
  const from = filters.from ?? null;
  return sql<Proposal[]>`
    SELECT
      id, created_at, expires_at, symbol, side, quantity::text AS quantity,
      limit_price::text AS limit_price, stop_price::text AS stop_price,
      rationale, confidence, status, decided_at, decided_by
    FROM proposal
    WHERE (${status}::text IS NULL OR status = ${status})
      AND (${symbol}::text IS NULL OR symbol = ${symbol})
      AND (${from}::text IS NULL OR created_at >= ${from}::timestamptz)
    ORDER BY created_at DESC
    LIMIT ${limit}
  `;
}

export interface Bar {
  trading_date: string; // ISO date
  close: string;
  volume: number;
}

/** Last N daily bars for a symbol, oldest first. */
export async function getRecentBars(
  symbol: string,
  limit = 30,
): Promise<Bar[]> {
  const sql = getSql();
  const rows = await sql<Bar[]>`
    SELECT trading_date::text AS trading_date,
           close::text AS close,
           volume
    FROM bar
    WHERE symbol = ${symbol.toUpperCase()}
    ORDER BY trading_date DESC
    LIMIT ${limit}
  `;
  return rows.reverse();
}

// ---------------------------------------------------------------------------
// Signal channels
// ---------------------------------------------------------------------------

export interface SignalChannel {
  id: number;
  handle: string;
  paused: boolean;
  added_at: string;
  last_run_at: string | null;
  signal_count_7d: number;
}

export async function listSignalChannels(): Promise<SignalChannel[]> {
  const sql = getSql();
  return sql<SignalChannel[]>`
    SELECT
      sc.id,
      sc.handle,
      sc.paused,
      sc.added_at::text AS added_at,
      sc.last_run_at::text AS last_run_at,
      COUNT(es.id)::int AS signal_count_7d
    FROM signalchannel sc
    LEFT JOIN externalsignal es
      ON es.channel = sc.handle
      AND es.posted_at >= NOW() - INTERVAL '7 days'
    GROUP BY sc.id
    ORDER BY sc.added_at ASC
  `;
}

// ---------------------------------------------------------------------------
// Proposal reasoning (m16)
// ---------------------------------------------------------------------------

export interface ProposalReasoning {
  id: number;
  proposal_id: number;
  prompt_text: string;
  response_text: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  created_at: Date;
}

export async function getProposalReasoning(
  proposalId: number,
): Promise<ProposalReasoning | null> {
  const sql = getSql();
  const rows = await sql<ProposalReasoning[]>`
    SELECT id, proposal_id, prompt_text, response_text, model,
           input_tokens::int AS input_tokens,
           output_tokens::int AS output_tokens,
           created_at
    FROM proposalreasoning
    WHERE proposal_id = ${proposalId}
    ORDER BY created_at DESC
    LIMIT 1
  `;
  return rows[0] ?? null;
}

// ---------------------------------------------------------------------------
// Shadow positions (m16)
// ---------------------------------------------------------------------------

export interface ShadowPosition {
  id: number;
  proposal_id: number;
  symbol: string;
  side: string;
  decision: string | null;
  opened_at: Date;
  opened_price: number;
  closed_at: Date | null;
  closed_price: number | null;
  pnl: number | null;
  mark_price: number | null;
  marked_at: Date | null;
}

export interface ShadowWindowStats {
  window_days: number;
  approved_pnl: number;
  approved_count: number;
  rejected_pnl: number;
  rejected_count: number;
}

export async function getShadowWindowStats(
  windowDays: number,
): Promise<ShadowWindowStats> {
  const sql = getSql();
  const rows = await sql<
    {
      decision: string | null;
      total_pnl: number;
      trade_count: number;
    }[]
  >`
    SELECT
      decision,
      COALESCE(SUM(pnl), 0)::float AS total_pnl,
      COUNT(*)::int AS trade_count
    FROM shadowposition
    WHERE closed_at IS NOT NULL
      AND opened_at >= NOW() - (${windowDays} || ' days')::interval
      AND decision IN ('approved', 'rejected')
    GROUP BY decision
  `;

  let approved_pnl = 0;
  let approved_count = 0;
  let rejected_pnl = 0;
  let rejected_count = 0;

  for (const row of rows) {
    if (row.decision === "approved") {
      approved_pnl = Number(row.total_pnl);
      approved_count = Number(row.trade_count);
    } else if (row.decision === "rejected") {
      rejected_pnl = Number(row.total_pnl);
      rejected_count = Number(row.trade_count);
    }
  }

  return {
    window_days: windowDays,
    approved_pnl,
    approved_count,
    rejected_pnl,
    rejected_count,
  };
}

export async function listClosedShadowPositions(
  limit = 200,
): Promise<ShadowPosition[]> {
  const sql = getSql();
  return sql<ShadowPosition[]>`
    SELECT
      id, proposal_id, symbol, side, decision,
      opened_at, opened_price::float AS opened_price,
      closed_at, closed_price::float AS closed_price,
      pnl::float AS pnl,
      mark_price::float AS mark_price,
      marked_at
    FROM shadowposition
    WHERE closed_at IS NOT NULL
    ORDER BY closed_at DESC
    LIMIT ${limit}
  `;
}
