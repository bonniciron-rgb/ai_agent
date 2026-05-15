/**
 * GET /api/analysis
 *
 * Returns the most recent DailyAnalysis rows (newest first) — the audit trail
 * behind each day's "trade / no trade" decision. Used by the /analysis page
 * and the "Today's analysis" card on /proposals.
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getSql } from "@/lib/db";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export interface DailyAnalysisRow {
  id: number;
  as_of: string; // YYYY-MM-DD
  symbols_considered: string[];
  proposals_generated: number;
  proposals_passed_risk: number;
  proposals_blocked_risk: number;
  agent_iterations: number;
  summary: string;
  model: string;
  created_at: string; // ISO timestamp
}

interface RawRow {
  id: number;
  as_of: string;
  symbols_considered_json: string;
  proposals_generated: number;
  proposals_passed_risk: number;
  proposals_blocked_risk: number;
  agent_iterations: number;
  summary: string;
  model: string;
  created_at: string;
}

function parseSymbols(json: string): string[] {
  try {
    const v = JSON.parse(json);
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export async function GET() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const sql = getSql();
    const rows = await sql<RawRow[]>`
      SELECT
        id,
        as_of::text AS as_of,
        symbols_considered_json,
        proposals_generated,
        proposals_passed_risk,
        proposals_blocked_risk,
        agent_iterations,
        summary,
        model,
        created_at::text AS created_at
      FROM dailyanalysis
      ORDER BY as_of DESC
      LIMIT 60
    `;
    const out: DailyAnalysisRow[] = rows.map((r) => ({
      id: r.id,
      as_of: r.as_of,
      symbols_considered: parseSymbols(r.symbols_considered_json),
      proposals_generated: r.proposals_generated,
      proposals_passed_risk: r.proposals_passed_risk,
      proposals_blocked_risk: r.proposals_blocked_risk,
      agent_iterations: r.agent_iterations,
      summary: r.summary,
      model: r.model,
      created_at: r.created_at,
    }));
    return NextResponse.json(out);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (message.includes("relation") && message.includes("does not exist")) {
      return NextResponse.json({ rows: [], setup_required: true });
    }
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
