/**
 * Magic-link verifier — accepts a token issued by the bot's /login command.
 *
 * Flow:
 *   1. Bot DM /login → bot replies with link /auth/magic?token=<jwt>
 *   2. User taps link from inside Telegram (opens in browser)
 *   3. This route verifies the JWT signature + expiry + uid
 *   4. Issues the dashboard session cookie (7-day TTL)
 *   5. Redirects to /
 */

import { NextRequest, NextResponse } from "next/server";
import { jwtVerify } from "jose";
import {
  SESSION_COOKIE,
  SESSION_TTL_MS,
  createSession,
} from "@/lib/auth";
import { env } from "@/lib/env";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const token = req.nextUrl.searchParams.get("token");
  if (!token) {
    return NextResponse.json(
      { ok: false, error: "missing_token" },
      { status: 400 },
    );
  }

  const secret = new TextEncoder().encode(env.SESSION_SECRET());

  let uid: string;
  try {
    const { payload } = await jwtVerify(token, secret);
    if (typeof payload.uid !== "string") {
      throw new Error("uid missing from payload");
    }
    uid = payload.uid;
  } catch {
    return NextResponse.json(
      { ok: false, error: "invalid_or_expired_token" },
      { status: 401 },
    );
  }

  const allowed = env.TELEGRAM_CHAT_ID();
  if (uid !== String(allowed)) {
    return NextResponse.json(
      { ok: false, error: "unauthorized_user" },
      { status: 403 },
    );
  }

  const session = await createSession({ uid });

  const res = NextResponse.redirect(new URL("/", req.url));
  res.cookies.set(SESSION_COOKIE, session, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: Math.floor(SESSION_TTL_MS / 1000),
  });
  return res;
}
