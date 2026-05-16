/**
 * GET /api/connection/t212
 *
 * Live connectivity test for Trading 212. Calls the T212 cash endpoint with
 * the dashboard's configured API key and reports success (with the account
 * balance) or the exact failure. Read-only — no orders, no writes.
 *
 * Requires T212_API_KEY (and optionally T212_ENV) in the dashboard's
 * environment — these are separate from the GitHub Actions secrets.
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export interface T212ConnectionResult {
  ok: boolean;
  configured: boolean;
  env: string; // "demo" | "live"
  free?: number;
  invested?: number;
  total?: number;
  status?: number; // HTTP status on failure
  message?: string;
  checkedAt: string; // ISO timestamp
}

export async function GET() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const checkedAt = new Date().toISOString();
  const apiKey = process.env.T212_API_KEY;
  const t212Env = (process.env.T212_ENV || "demo").toLowerCase();
  const base =
    t212Env === "live"
      ? "https://live.trading212.com"
      : "https://demo.trading212.com";

  if (!apiKey) {
    const result: T212ConnectionResult = {
      ok: false,
      configured: false,
      env: t212Env,
      message:
        "T212_API_KEY is not set in the dashboard environment. Add it in Vercel → Settings → Environment Variables, then redeploy.",
      checkedAt,
    };
    return NextResponse.json(result);
  }

  const headers = { Authorization: apiKey, Accept: "application/json" };
  try {
    const res = await fetch(`${base}/api/v0/equity/account/cash`, {
      headers,
      cache: "no-store",
    });
    if (!res.ok) {
      const body = await res.text();
      const result: T212ConnectionResult = {
        ok: false,
        configured: true,
        env: t212Env,
        status: res.status,
        message:
          res.status === 401
            ? "401 Unauthorized — the API key is invalid, expired, or for the wrong environment (demo vs live). Check T212_ENV matches the key."
            : `T212 returned ${res.status}: ${body.slice(0, 200)}`,
        checkedAt,
      };
      return NextResponse.json(result);
    }
    const cash = (await res.json()) as Record<string, unknown>;
    const result: T212ConnectionResult = {
      ok: true,
      configured: true,
      env: t212Env,
      free: Number(cash.free ?? 0),
      invested: Number(cash.invested ?? 0),
      total: Number(cash.total ?? 0),
      message: "Connected — T212 account reachable.",
      checkedAt,
    };
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const result: T212ConnectionResult = {
      ok: false,
      configured: true,
      env: t212Env,
      message: `Request to T212 failed: ${message}`,
      checkedAt,
    };
    return NextResponse.json(result);
  }
}
