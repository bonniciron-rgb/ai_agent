/**
 * Edge middleware — protect every page route except /login and the
 * auth callback endpoints.  Static assets and the Python webhook are
 * excluded via the matcher config below.
 */

import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

const PUBLIC_PATHS = [
  "/login",
  "/api/auth/telegram",
  "/api/auth/logout",
  "/auth/magic",
];

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }

  const session = await verifySession(req.cookies.get(SESSION_COOKIE)?.value);
  if (session) return NextResponse.next();

  const loginUrl = new URL("/login", req.url);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  // Match everything except: Next internals, static files, and the Python
  // serverless webhook (which Vercel routes to its own runtime).
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/telegram_webhook).*)",
  ],
};
