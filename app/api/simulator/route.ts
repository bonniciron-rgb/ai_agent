/**
 * GET /api/simulator?symbol=AAPL&days=180
 *
 * Returns OHLCV bars + agent proposals for the requested symbol/period.
 * Also returns the list of available symbols (for the symbol picker).
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { verifySession, SESSION_COOKIE } from "@/lib/auth";
import {
  getSimulatorBars,
  getSimulatorProposals,
  getSimulatorSymbols,
  type SimulatorBar,
  type SimulatorProposal,
} from "@/lib/queries";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export interface SimulatorResponse {
  bars: SimulatorBar[];
  proposals: SimulatorProposal[];
  symbols: string[];
}

export async function GET(req: Request) {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const symbol = (searchParams.get("symbol") ?? "").toUpperCase();
  const days = Math.min(Math.max(Number(searchParams.get("days") ?? 180), 30), 730);

  if (!symbol) {
    return NextResponse.json({ error: "symbol is required" }, { status: 400 });
  }

  try {
    const [bars, proposals, symbols] = await Promise.all([
      getSimulatorBars(symbol, days),
      getSimulatorProposals(symbol, days),
      getSimulatorSymbols(),
    ]);
    return NextResponse.json({ bars, proposals, symbols } satisfies SimulatorResponse);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
