/**
 * GET /api/llm-usage
 *
 * Returns the last 30 days of LLM token usage grouped by (date, model, pass_type).
 * Used for cost-monitoring dashboards.  A future PR will build the UI page.
 *
 * Query params:
 *   days  — number of days to look back (default 30, max 90)
 */

import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { verifySession, SESSION_COOKIE } from "@/lib/auth";
import { getSql } from "@/lib/db";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export interface LlmUsageRow {
  occurred_on: string; // YYYY-MM-DD
  model: string;
  pass_type: string; // "screening" | "decision" | "other"
  total_input_tokens: number;
  total_output_tokens: number;
  total_cache_creation_tokens: number;
  total_cache_read_tokens: number;
  total_cost_usd: string; // Decimal serialised as string
  call_count: number;
}

export async function GET(req: NextRequest) {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const rawDays = parseInt(searchParams.get("days") ?? "30", 10);
  const days = Math.min(Math.max(rawDays, 1), 90);

  try {
    const sql = await getSql();
    const rows = await sql<LlmUsageRow[]>`
      SELECT
        occurred_on::text                       AS occurred_on,
        model,
        pass_type,
        SUM(input_tokens)::int                  AS total_input_tokens,
        SUM(output_tokens)::int                 AS total_output_tokens,
        SUM(cache_creation_tokens)::int         AS total_cache_creation_tokens,
        SUM(cache_read_input_tokens)::int       AS total_cache_read_tokens,
        SUM(cost_usd)::text                     AS total_cost_usd,
        COUNT(*)::int                           AS call_count
      FROM llmusage
      WHERE occurred_on >= CURRENT_DATE - (${days} || ' days')::interval
      GROUP BY occurred_on, model, pass_type
      ORDER BY occurred_on DESC, model, pass_type
    `;

    return NextResponse.json({ rows, days });
  } catch (err) {
    console.error("llm-usage query failed:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
