/**
 * Telegram Login Widget callback.
 *
 * The widget redirects the browser here with auth params in the query string:
 *   ?id=&first_name=&username=&auth_date=&hash=...
 *
 * We verify the HMAC, check the user is the authorized chat owner, then
 * set an httpOnly session cookie and redirect to "/".
 */

import { NextRequest, NextResponse } from "next/server";
import {
  SESSION_COOKIE,
  SESSION_TTL_MS,
  TelegramAuthData,
  createSession,
  isAuthRecent,
  verifyTelegramAuth,
} from "@/lib/auth";
import { env } from "@/lib/env";

export const runtime = "nodejs";

export async function GET(req: NextRequest) {
  const params = req.nextUrl.searchParams;

  const id = params.get("id");
  const auth_date = params.get("auth_date");
  const hash = params.get("hash");
  if (!id || !auth_date || !hash) {
    return NextResponse.json(
      { ok: false, error: "missing_required_params" },
      { status: 400 },
    );
  }

  const data: TelegramAuthData = {
    id: Number(id),
    auth_date: Number(auth_date),
    hash,
    first_name: params.get("first_name") || undefined,
    last_name: params.get("last_name") || undefined,
    username: params.get("username") || undefined,
    photo_url: params.get("photo_url") || undefined,
  };

  const botToken = env.TELEGRAM_BOT_TOKEN();
  const allowedChat = env.TELEGRAM_CHAT_ID();

  if (!(await verifyTelegramAuth(data, botToken))) {
    return NextResponse.json(
      { ok: false, error: "invalid_signature" },
      { status: 401 },
    );
  }

  if (!isAuthRecent(data.auth_date)) {
    return NextResponse.json(
      { ok: false, error: "auth_expired" },
      { status: 401 },
    );
  }

  if (String(data.id) !== String(allowedChat)) {
    return NextResponse.json(
      { ok: false, error: "unauthorized_user" },
      { status: 403 },
    );
  }

  const token = await createSession({
    uid: String(data.id),
    username: data.username,
  });

  const res = NextResponse.redirect(new URL("/", req.url));
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: Math.floor(SESSION_TTL_MS / 1000),
  });
  return res;
}
