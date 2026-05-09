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
  return NextResponse.json(rows);
}

export async function POST(req: NextRequest) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => null);
  let handle: string = body?.handle ?? "";
  handle = handle.trim();
  if (!handle) return NextResponse.json({ error: "handle is required" }, { status: 400 });
  if (!handle.startsWith("@")) handle = `@${handle}`;

  const sql = getSql();
  const existing = await sql`SELECT id FROM signalchannel WHERE handle = ${handle}`;
  if (existing.length > 0) {
    return NextResponse.json({ error: "Channel already exists" }, { status: 409 });
  }

  const [row] = await sql`
    INSERT INTO signalchannel (handle, paused, added_at)
    VALUES (${handle}, false, NOW())
    RETURNING id, handle, paused, added_at::text AS added_at, last_run_at
  `;
  return NextResponse.json(row, { status: 201 });
}
