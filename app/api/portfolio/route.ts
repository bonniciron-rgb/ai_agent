/**
 * GET /api/portfolio
 *
 * Returns the live Trading 212 portfolio — cash balances + open positions —
 * for the Portfolio dashboard page. Each position is flagged with whether its
 * symbol is already in the watchlist. Read-only; HTTP Basic auth.
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getSql } from "@/lib/db";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export interface PortfolioPosition {
  ticker: string; // raw T212 ticker, e.g. "AAPL_US_EQ"
  symbol: string; // plain symbol, e.g. "AAPL"
  quantity: number;
  averagePrice: number;
  currentPrice: number;
  marketValue: number;
  pnl: number;
  pnlPct: number;
  inWatchlist: boolean;
}

export interface PortfolioResult {
  ok: boolean;
  configured: boolean;
  env: string;
  cash?: { free: number; invested: number; total: number };
  positions: PortfolioPosition[];
  status?: number;
  message?: string;
  checkedAt: string;
}

/** Strip the T212 venue suffix: "AAPL_US_EQ" -> "AAPL". */
function plainSymbol(ticker: string): string {
  return (ticker.split("_")[0] || ticker).toUpperCase();
}

export async function GET() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const checkedAt = new Date().toISOString();
  const apiKey = process.env.T212_API_KEY?.trim();
  const apiSecret = process.env.T212_API_SECRET?.trim();
  const env = (process.env.T212_ENV || "demo").toLowerCase();
  const base =
    env === "live"
      ? "https://live.trading212.com"
      : "https://demo.trading212.com";

  if (!apiKey || !apiSecret) {
    const result: PortfolioResult = {
      ok: false,
      configured: false,
      env,
      positions: [],
      message:
        "T212_API_KEY and T212_API_SECRET must both be set in the dashboard environment (Vercel → Settings → Environment Variables).",
      checkedAt,
    };
    return NextResponse.json(result);
  }

  const token = Buffer.from(`${apiKey}:${apiSecret}`).toString("base64");
  const headers = { Authorization: `Basic ${token}`, Accept: "application/json" };

  try {
    const [cashRes, posRes] = await Promise.all([
      fetch(`${base}/api/v0/equity/account/cash`, { headers, cache: "no-store" }),
      fetch(`${base}/api/v0/equity/portfolio`, { headers, cache: "no-store" }),
    ]);

    if (!cashRes.ok || !posRes.ok) {
      const bad = !cashRes.ok ? cashRes : posRes;
      const body = await bad.text();
      const result: PortfolioResult = {
        ok: false,
        configured: true,
        env,
        positions: [],
        status: bad.status,
        message:
          bad.status === 401
            ? "401 Unauthorized — check the T212 key + secret and that T212_ENV matches the account."
            : `T212 returned ${bad.status}: ${body.slice(0, 200)}`,
        checkedAt,
      };
      return NextResponse.json(result);
    }

    const cash = (await cashRes.json()) as Record<string, unknown>;
    const rawPositions = (await posRes.json()) as unknown;

    // Cross-reference the watchlist so the UI can flag un-tracked holdings.
    let watchSymbols = new Set<string>();
    try {
      const sql = getSql();
      const rows = await sql<{ symbol: string }[]>`SELECT symbol FROM watchlistticker`;
      watchSymbols = new Set(rows.map((r) => r.symbol.toUpperCase()));
    } catch {
      // watchlistticker table may not exist yet — leave every flag false.
    }

    const positions: PortfolioPosition[] = (
      Array.isArray(rawPositions) ? rawPositions : []
    ).map((p: Record<string, unknown>) => {
      const ticker = String(p.ticker ?? "");
      const symbol = plainSymbol(ticker);
      const quantity = Number(p.quantity ?? 0);
      const averagePrice = Number(p.averagePrice ?? 0);
      const currentPrice = Number(p.currentPrice ?? 0);
      const marketValue = quantity * currentPrice;
      const cost = quantity * averagePrice;
      const pnl = p.ppl !== undefined ? Number(p.ppl) : marketValue - cost;
      const pnlPct = cost > 0 ? (pnl / cost) * 100 : 0;
      return {
        ticker,
        symbol,
        quantity,
        averagePrice,
        currentPrice,
        marketValue,
        pnl,
        pnlPct,
        inWatchlist: watchSymbols.has(symbol),
      };
    });

    const result: PortfolioResult = {
      ok: true,
      configured: true,
      env,
      cash: {
        free: Number(cash.free ?? 0),
        invested: Number(cash.invested ?? 0),
        total: Number(cash.total ?? 0),
      },
      positions,
      checkedAt,
    };
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const result: PortfolioResult = {
      ok: false,
      configured: true,
      env,
      positions: [],
      message: `Request to T212 failed: ${message}`,
      checkedAt,
    };
    return NextResponse.json(result);
  }
}
