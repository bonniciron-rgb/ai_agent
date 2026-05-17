/**
 * Finnhub insider-transactions tracker — SEC Form 4 activity.
 *
 * Surfaces recent insider buys/sells for the active watchlist. An insider
 * open-market purchase (transaction code "P") — a leader buying their own
 * company's stock — is a notable conviction signal. Cached 6h; degrades
 * gracefully without FINNHUB_API_KEY.
 */

import { getSql } from "@/lib/db";

const KEY = process.env.FINNHUB_API_KEY || "";
const REVALIDATE = 6 * 60 * 60; // 6 hours
const MAX_SYMBOLS = 20;
const LOOKBACK_DAYS = 90;
const MAX_ROWS = 60;

export interface InsiderTxn {
  symbol: string;
  name: string;
  date: string; // YYYY-MM-DD transaction date
  label: string; // "Buy" | "Sell"
  isBuy: boolean;
  shares: number;
  value: number; // USD
}

export interface InsiderActivity {
  txns: InsiderTxn[]; // sorted newest first
  configured: boolean;
  error?: string;
}

async function activeWatchlist(): Promise<string[]> {
  try {
    const sql = getSql();
    const rows = await sql<{ symbol: string }[]>`
      SELECT symbol FROM watchlistticker WHERE paused = false ORDER BY symbol
    `;
    return rows.map((r) => r.symbol).slice(0, MAX_SYMBOLS);
  } catch {
    return [];
  }
}

async function fetchSymbol(
  symbol: string,
  from: string,
): Promise<InsiderTxn[]> {
  const url =
    `https://finnhub.io/api/v1/stock/insider-transactions` +
    `?symbol=${encodeURIComponent(symbol)}&from=${from}&token=${KEY}`;
  try {
    const res = await fetch(url, { next: { revalidate: REVALIDATE } });
    if (!res.ok) return [];
    const body = (await res.json()) as {
      data?: {
        name?: string;
        transactionDate?: string;
        transactionCode?: string;
        transactionPrice?: number;
        change?: number;
      }[];
    };
    const out: InsiderTxn[] = [];
    for (const d of body.data ?? []) {
      const code = (d.transactionCode ?? "").toUpperCase();
      // P = open-market purchase, S = open-market sale — the meaningful signals.
      if (code !== "P" && code !== "S") continue;
      const shares = Math.abs(d.change ?? 0);
      out.push({
        symbol,
        name: d.name ?? "—",
        date: d.transactionDate ?? "",
        label: code === "P" ? "Buy" : "Sell",
        isBuy: code === "P",
        shares,
        value: shares * (d.transactionPrice ?? 0),
      });
    }
    return out;
  } catch {
    return [];
  }
}

export async function getInsiderActivity(): Promise<InsiderActivity> {
  if (!KEY) return { txns: [], configured: false };

  const symbols = await activeWatchlist();
  if (symbols.length === 0) {
    return { txns: [], configured: true, error: "no active watchlist symbols" };
  }

  const from = new Date(Date.now() - LOOKBACK_DAYS * 86_400_000)
    .toISOString()
    .slice(0, 10);
  const perSymbol = await Promise.all(symbols.map((s) => fetchSymbol(s, from)));
  const txns = perSymbol
    .flat()
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, MAX_ROWS);
  return { txns, configured: true };
}
