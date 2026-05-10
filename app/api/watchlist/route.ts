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
      symbol,
      sector,
      notes,
      tags_json,
      paused,
      added_at::text AS added_at,
      updated_at::text AS updated_at
    FROM watchlistticker
    ORDER BY symbol ASC
  `;
  return NextResponse.json(rows);
}

export async function POST(req: NextRequest) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json().catch(() => null);
  let symbol: string = body?.symbol ?? "";
  symbol = symbol.trim().toUpperCase();
  if (!symbol) return NextResponse.json({ error: "symbol is required" }, { status: 400 });
  if (symbol.length > 16)
    return NextResponse.json({ error: "symbol must be 16 characters or fewer" }, { status: 400 });
  if (!/^[A-Z0-9.\-]+$/.test(symbol))
    return NextResponse.json({ error: "symbol contains invalid characters" }, { status: 400 });

  const sql = getSql();
  const existing = await sql`SELECT id FROM watchlistticker WHERE symbol = ${symbol}`;
  if (existing.length > 0) {
    return NextResponse.json({ error: "Ticker already exists" }, { status: 409 });
  }

  const sector: string | null = body?.sector ?? null;
  const notes: string | null = body?.notes ?? null;
  const tags: string[] = Array.isArray(body?.tags) ? body.tags : [];

  const [row] = await sql`
    INSERT INTO watchlistticker (symbol, sector, notes, tags_json, paused, added_at, updated_at)
    VALUES (
      ${symbol},
      ${sector},
      ${notes},
      ${JSON.stringify(tags)},
      false,
      NOW(),
      NOW()
    )
    RETURNING id, symbol, sector, notes, tags_json, paused, added_at::text AS added_at, updated_at::text AS updated_at
  `;
  return NextResponse.json(row, { status: 201 });
}
