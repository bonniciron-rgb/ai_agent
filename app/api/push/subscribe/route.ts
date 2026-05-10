import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getSql } from "@/lib/db";

export const runtime = "nodejs";

async function getSession() {
  const token = cookies().get(SESSION_COOKIE)?.value;
  return token ? verifySession(token) : null;
}

interface SubscribeBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export async function POST(req: NextRequest) {
  const session = await getSession();
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = (await req.json().catch(() => null)) as SubscribeBody | null;
  if (!body?.endpoint || !body?.keys?.p256dh || !body?.keys?.auth) {
    return NextResponse.json({ error: "Invalid subscription" }, { status: 400 });
  }

  const ua = req.headers.get("user-agent")?.slice(0, 256) ?? null;
  const sql = getSql();
  await sql`
    INSERT INTO pushsubscription (endpoint, auth_key, p256dh_key, user_agent, created_at)
    VALUES (${body.endpoint}, ${body.keys.auth}, ${body.keys.p256dh}, ${ua}, NOW())
    ON CONFLICT (endpoint) DO NOTHING
  `;

  return NextResponse.json({ ok: true }, { status: 201 });
}
