/**
 * GET /api/reconciliation
 *
 * Returns the 30 most recent reconciliation runs, newest first.
 * Used by the /reconciliation dashboard page.
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { verifySession, SESSION_COOKIE } from "@/lib/auth";
import { getSql } from "@/lib/db";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export interface ReconciliationRow {
  id: number;
  run_at: string; // ISO timestamp
  status: "ok" | "drift_detected" | "error";
  position_drifts: number;
  order_drifts: number;
  details: string | null; // JSON string
}

export async function GET() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const sql = getSql();
    const rows = await sql<ReconciliationRow[]>`
      SELECT
        id,
        run_at::text AS run_at,
        status,
        position_drifts,
        order_drifts,
        details
      FROM reconciliation
      ORDER BY run_at DESC
      LIMIT 30
    `;
    return NextResponse.json(rows);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
