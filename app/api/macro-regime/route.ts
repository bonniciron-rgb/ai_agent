import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getSql } from "@/lib/db";

export const runtime = "nodejs";

async function getSession() {
  const token = cookies().get(SESSION_COOKIE)?.value;
  return token ? verifySession(token) : null;
}

export async function GET(_req: NextRequest) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const sql = getSql();
  const rows = await sql`
    SELECT
      id,
      as_of::text AS as_of,
      regime,
      spy_close::text AS spy_close,
      spy_sma_50::text AS spy_sma_50,
      spy_sma_200::text AS spy_sma_200,
      spy_above_200sma,
      spy_50_over_200sma,
      vix_close::text AS vix_close,
      vix_sma_20::text AS vix_sma_20,
      notes_json,
      created_at::text AS created_at
    FROM macroregimesnapshot
    ORDER BY as_of DESC
    LIMIT 30
  `;

  const latest = rows[0] ?? null;
  const history = [...rows].reverse(); // oldest first for the chart
  return NextResponse.json({ latest, history });
}
