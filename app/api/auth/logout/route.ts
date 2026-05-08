/**
 * Logout — clears the session cookie and redirects to /login.
 * Accepts both GET (link) and POST (form submission).
 */

import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/auth";

export const runtime = "nodejs";

function clearSessionAndRedirect(req: NextRequest) {
  const res = NextResponse.redirect(new URL("/login", req.url));
  res.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return res;
}

export async function GET(req: NextRequest) {
  return clearSessionAndRedirect(req);
}

export async function POST(req: NextRequest) {
  return clearSessionAndRedirect(req);
}
