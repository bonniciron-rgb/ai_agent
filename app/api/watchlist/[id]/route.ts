import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getSql } from "@/lib/db";

export const runtime = "nodejs";

async function getSession() {
  const token = cookies().get(SESSION_COOKIE)?.value;
  return token ? verifySession(token) : null;
}

export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const id = parseInt(params.id, 10);
  if (isNaN(id)) return NextResponse.json({ error: "Invalid id" }, { status: 400 });

  const body = await req.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: "Invalid request body" }, { status: 400 });
  }

  const sql = getSql();
  const existing = await sql`SELECT id FROM watchlistticker WHERE id = ${id}`;
  if (existing.length === 0) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const hasSector = "sector" in body;
  const hasNotes = "notes" in body;
  const hasTags = "tags" in body;
  const hasPaused = "paused" in body && typeof body.paused === "boolean";

  const sector: string | null = hasSector ? (body.sector ?? null) : null;
  const notes: string | null = hasNotes ? (body.notes ?? null) : null;
  const tagsJson: string = hasTags ? JSON.stringify(Array.isArray(body.tags) ? body.tags : []) : "[]";
  const paused: boolean = hasPaused ? (body.paused as boolean) : false;

  const [row] = await sql`
    UPDATE watchlistticker
    SET
      sector    = CASE WHEN ${hasSector}  THEN ${sector}   ELSE sector    END,
      notes     = CASE WHEN ${hasNotes}   THEN ${notes}    ELSE notes     END,
      tags_json = CASE WHEN ${hasTags}    THEN ${tagsJson} ELSE tags_json END,
      paused    = CASE WHEN ${hasPaused}  THEN ${paused}   ELSE paused    END,
      updated_at = NOW()
    WHERE id = ${id}
    RETURNING
      id,
      symbol,
      sector,
      notes,
      tags_json,
      paused,
      added_at::text  AS added_at,
      updated_at::text AS updated_at
  `;
  if (!row) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return NextResponse.json(row);
}

export async function DELETE(req: NextRequest, { params }: { params: { id: string } }) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const id = parseInt(params.id, 10);
  if (isNaN(id)) return NextResponse.json({ error: "Invalid id" }, { status: 400 });

  const sql = getSql();
  const result = await sql`DELETE FROM watchlistticker WHERE id = ${id}`;
  if (result.count === 0) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return new NextResponse(null, { status: 204 });
}
