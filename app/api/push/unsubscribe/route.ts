import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getSql } from "@/lib/db";

export const runtime = "nodejs";

async function getSession() {
  const token = cookies().get(SESSION_COOKIE)?.value;
  return token ? verifySession(token) : null;
}

export async function POST(req: NextRequest) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await req.json().catch(() => null)) as { endpoint?: string } | null;
  const endpoint = body?.endpoint?.trim();
  if (!endpoint) return NextResponse.json({ error: "endpoint required" }, { status: 400 });

  const sql = getSql();
  await sql`DELETE FROM pushsubscription WHERE endpoint = ${endpoint}`;
  return NextResponse.json({ ok: true });
}
