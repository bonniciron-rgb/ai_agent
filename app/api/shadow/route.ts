/**
 * GET /api/shadow
 *
 * Returns shadow P&L data for the dashboard:
 *   - stats: 7d / 30d / 90d window summaries
 *   - positions: paginated closed shadow positions (newest first)
 *
 * Query params:
 *   limit  — max positions to return (default 200)
 */

import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import {
  getShadowWindowStats,
  listClosedShadowPositions,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const rawLimit = parseInt(searchParams.get("limit") ?? "200", 10);
  const limit = Math.min(Math.max(rawLimit, 1), 500);

  try {
    const [stats7d, stats30d, stats90d, positions] = await Promise.all([
      getShadowWindowStats(7),
      getShadowWindowStats(30),
      getShadowWindowStats(90),
      listClosedShadowPositions(limit),
    ]);

    return NextResponse.json({
      stats: [stats7d, stats30d, stats90d],
      positions,
    });
  } catch (err) {
    console.error("shadow query failed:", err);
    return NextResponse.json({ error: "Database error" }, { status: 500 });
  }
}
