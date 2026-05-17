/**
 * GET /api/portfolio
 *
 * Returns the live Trading 212 portfolio — cash balances + open positions —
 * for the Portfolio dashboard page. Each position is flagged with whether its
 * symbol is already in the watchlist. Read-only; HTTP Basic auth.
 *
 * Position prices are normalised to GBP: London listings quote in pence (GBX,
 * /100) and other currencies are converted via live FX rates, so a pence
 * price is not mistaken for pounds.
 *
 * Also upserts a daily snapshot of total account value into
 * `portfoliovaluesnapshot` so the UI can show 1-day / 7-day change.
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
  name: string; // human-readable instrument name, e.g. "Apple Inc."
  currency: string; // instrument quote currency, e.g. "USD", "GBX"
  quantity: number;
  averagePrice: number; // converted to GBP
  currentPrice: number; // converted to GBP
  marketValue: number; // GBP
  pnl: number;
  pnlPct: number;
  inWatchlist: boolean;
  usListed: boolean; // US-listed — the agent can fetch data and screen it
}

/** Change in total account value vs an earlier daily snapshot. */
export interface ValueChange {
  abs: number;
  pct: number;
  asOf: string; // the snapshot date this change is measured against
}

export interface PortfolioResult {
  ok: boolean;
  configured: boolean;
  env: string;
  cash?: { free: number; invested: number; total: number };
  positions: PortfolioPosition[];
  valueChange?: { d1: ValueChange | null; d7: ValueChange | null };
  status?: number;
  message?: string;
  checkedAt: string;
}

/**
 * Strip the T212 venue suffix and normalise to a plain symbol.
 *   "AAPL_US_EQ" -> "AAPL"
 *   "VWRPl_EQ"   -> "VWRP"  (T212 marks London listings with a trailing "l")
 */
function plainSymbol(ticker: string): string {
  let seg = ticker.split("_")[0] || ticker;
  if (seg.length > 1 && seg.endsWith("l")) seg = seg.slice(0, -1);
  return seg.toUpperCase();
}

// Module-level cache of T212 instrument metadata (name + quote currency).
// The metadata endpoint returns the whole instrument universe (large), so it
// is fetched at most once per day per warm serverless instance.
interface InstrumentMeta {
  name: string;
  currency: string;
}
let instrumentCache: {
  at: number;
  meta: Map<string, InstrumentMeta>;
} | null = null;
const META_TTL_MS = 24 * 60 * 60 * 1000;

async function getInstrumentMeta(
  base: string,
  headers: Record<string, string>,
): Promise<Map<string, InstrumentMeta>> {
  if (instrumentCache && Date.now() - instrumentCache.at < META_TTL_MS) {
    return instrumentCache.meta;
  }
  const meta = new Map<string, InstrumentMeta>();
  try {
    const res = await fetch(`${base}/api/v0/equity/metadata/instruments`, {
      headers,
      cache: "no-store",
    });
    if (res.ok) {
      const list = (await res.json()) as unknown;
      if (Array.isArray(list)) {
        for (const it of list as Record<string, unknown>[]) {
          const t = typeof it.ticker === "string" ? it.ticker : "";
          if (!t) continue;
          const name =
            (typeof it.name === "string" && it.name.trim()) ||
            (typeof it.shortName === "string" && it.shortName.trim()) ||
            "";
          const currency =
            typeof it.currencyCode === "string" ? it.currencyCode.trim() : "";
          meta.set(t, { name, currency });
        }
      }
      if (meta.size > 0) instrumentCache = { at: Date.now(), meta };
    }
  } catch {
    // Metadata unavailable — positions fall back to bare symbol + raw price.
  }
  return meta;
}

// Module-level cache of FX rates expressed as 1 GBP = <rate> <currency>.
let fxCache: { at: number; rates: Record<string, number> } | null = null;
const FX_TTL_MS = 12 * 60 * 60 * 1000;

async function getGbpFxRates(): Promise<Record<string, number>> {
  if (fxCache && Date.now() - fxCache.at < FX_TTL_MS) return fxCache.rates;
  try {
    const res = await fetch("https://api.frankfurter.app/latest?base=GBP", {
      cache: "no-store",
    });
    if (res.ok) {
      const body = (await res.json()) as { rates?: Record<string, number> };
      if (body.rates && Object.keys(body.rates).length > 0) {
        fxCache = { at: Date.now(), rates: body.rates };
        return body.rates;
      }
    }
  } catch {
    // FX unavailable — non-GBP positions fall back to their raw price.
  }
  return fxCache?.rates ?? {};
}

/**
 * Convert an instrument-currency price to GBP.
 *   GBP        -> unchanged
 *   GBX / GBp  -> pence: divide by 100 (a unit, not an FX rate — London
 *                 listings such as ETFs quote in pence)
 *   other      -> divide by the GBP->currency rate; if the rate is unknown
 *                 the price is returned unchanged.
 */
function toGbp(
  price: number,
  currency: string,
  fx: Record<string, number>,
): number {
  const c = currency.trim();
  if (c === "GBX" || c === "GBp" || c.toUpperCase() === "GBX") return price / 100;
  const cu = c.toUpperCase();
  if (!cu || cu === "GBP") return price;
  const rate = fx[cu];
  return rate && rate > 0 ? price / rate : price;
}

function changeVs(
  current: number,
  past?: { as_of: string; total_value: number },
): ValueChange | null {
  if (!past || past.total_value <= 0) return null;
  const abs = current - past.total_value;
  return { abs, pct: (abs / past.total_value) * 100, asOf: past.as_of };
}

/**
 * Upsert today's portfolio-value snapshot and return the 1-day / 7-day
 * change vs earlier snapshots. Best-effort — a DB failure yields `undefined`
 * and the comparison is simply omitted.
 */
async function recordSnapshot(
  total: number,
  free: number,
  invested: number,
  positionCount: number,
): Promise<{ d1: ValueChange | null; d7: ValueChange | null } | undefined> {
  try {
    const sql = getSql();
    await sql`
      CREATE TABLE IF NOT EXISTS portfoliovaluesnapshot (
        id SERIAL PRIMARY KEY,
        as_of DATE NOT NULL UNIQUE,
        total_value DOUBLE PRECISION NOT NULL,
        free_cash DOUBLE PRECISION NOT NULL,
        invested DOUBLE PRECISION NOT NULL,
        position_count INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `;
    await sql`
      INSERT INTO portfoliovaluesnapshot
        (as_of, total_value, free_cash, invested, position_count, created_at)
      VALUES (CURRENT_DATE, ${total}, ${free}, ${invested}, ${positionCount}, NOW())
      ON CONFLICT (as_of) DO UPDATE SET
        total_value = EXCLUDED.total_value,
        free_cash = EXCLUDED.free_cash,
        invested = EXCLUDED.invested,
        position_count = EXCLUDED.position_count,
        created_at = NOW()
    `;
    const history = await sql<{ as_of: string; total_value: number }[]>`
      SELECT as_of::text AS as_of, total_value
      FROM portfoliovaluesnapshot
      WHERE as_of < CURRENT_DATE
      ORDER BY as_of DESC
      LIMIT 30
    `;
    const cutoff = new Date();
    cutoff.setUTCDate(cutoff.getUTCDate() - 7);
    const cutoff7 = cutoff.toISOString().slice(0, 10);
    return {
      d1: changeVs(total, history[0]),
      d7: changeVs(total, history.find((h) => h.as_of <= cutoff7)),
    };
  } catch {
    return undefined;
  }
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
    const [cashRes, posRes, instrumentMeta, fxRates] = await Promise.all([
      fetch(`${base}/api/v0/equity/account/cash`, { headers, cache: "no-store" }),
      fetch(`${base}/api/v0/equity/portfolio`, { headers, cache: "no-store" }),
      getInstrumentMeta(base, headers),
      getGbpFxRates(),
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
      const meta = instrumentMeta.get(ticker);
      const name = meta?.name || symbol;
      const currency = meta?.currency || "";
      const quantity = Number(p.quantity ?? 0);
      const averagePrice = toGbp(Number(p.averagePrice ?? 0), currency, fxRates);
      const currentPrice = toGbp(Number(p.currentPrice ?? 0), currency, fxRates);
      const marketValue = quantity * currentPrice;
      const cost = quantity * averagePrice;
      const pnl = p.ppl !== undefined ? Number(p.ppl) : marketValue - cost;
      const pnlPct = cost > 0 ? (pnl / cost) * 100 : 0;
      return {
        ticker,
        symbol,
        name,
        currency,
        quantity,
        averagePrice,
        currentPrice,
        marketValue,
        pnl,
        pnlPct,
        inWatchlist: watchSymbols.has(symbol),
        usListed: ticker.includes("_US_"),
      };
    });

    const free = Number(cash.free ?? 0);
    const invested = Number(cash.invested ?? 0);
    const total = Number(cash.total ?? 0);
    const valueChange = await recordSnapshot(
      total,
      free,
      invested,
      positions.length,
    );

    const result: PortfolioResult = {
      ok: true,
      configured: true,
      env,
      cash: { free, invested, total },
      positions,
      valueChange,
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
