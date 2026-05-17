"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  PortfolioPosition,
  PortfolioResult,
} from "@/app/api/portfolio/route";

function money(n: number): string {
  return n.toLocaleString("en-GB", {
    style: "currency",
    currency: "GBP",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function signed(n: number): string {
  return (n >= 0 ? "+" : "") + money(n);
}

function pct(n: number): string {
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

function pnlColor(n: number): string {
  if (n > 0) return "text-emerald-400";
  if (n < 0) return "text-rose-400";
  return "text-zinc-400";
}

export function PortfolioClient() {
  const [data, setData] = useState<PortfolioResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [addMsg, setAddMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setAddMsg(null);
    try {
      const res = await fetch("/api/portfolio", { cache: "no-store" });
      const json = (await res.json()) as PortfolioResult;
      setData(json);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const positions = data?.positions ?? [];
  // Only US-listed holdings can be screened — the agent's data pipeline
  // (yfinance/Stooq) and factor signals are built for US equities. London
  // ETFs etc. are shown but never pushed onto the screening watchlist.
  const addable = positions.filter((p) => !p.inWatchlist && p.usListed);
  const nonUs = positions.filter((p) => !p.usListed);

  async function addHoldings() {
    if (addable.length === 0) return;
    setAdding(true);
    setAddMsg(null);
    let added = 0;
    let skipped = 0;
    let failed = 0;
    for (const p of addable) {
      try {
        const res = await fetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbol: p.symbol,
            sector: null,
            notes: "Held in Trading 212 portfolio",
            tags: ["holding"],
          }),
        });
        if (res.ok) added += 1;
        else if (res.status === 409) skipped += 1;
        else failed += 1;
      } catch {
        failed += 1;
      }
    }
    const parts: string[] = [];
    if (added) parts.push(`${added} added`);
    if (skipped) parts.push(`${skipped} already tracked`);
    if (failed) parts.push(`${failed} failed`);
    setAddMsg(parts.join(", ") || "Nothing to add.");
    setAdding(false);
    await load();
  }

  if (loading && !data) {
    return (
      <div className="rounded-md border border-zinc-800 px-4 py-6 text-center text-sm text-zinc-500">
        Loading portfolio…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md bg-rose-950 border border-rose-800 px-4 py-3 text-sm text-rose-300">
        {error}
      </div>
    );
  }

  if (!data) return null;

  // Connection / configuration problems surface as ok:false.
  if (!data.ok) {
    return (
      <div className="space-y-4">
        <div className="rounded-md bg-amber-950 border border-amber-800 px-4 py-3 text-sm text-amber-300">
          <p className="font-medium">
            {data.configured
              ? "Couldn't load the Trading 212 portfolio."
              : "Trading 212 is not configured."}
          </p>
          {data.message && <p className="mt-1 text-amber-400/90">{data.message}</p>}
        </div>
        <button
          onClick={() => void load()}
          className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 text-sm font-medium transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Account summary */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-300 uppercase tracking-wider">
            Account
          </h2>
          <span className="text-xs rounded px-1.5 py-0.5 bg-zinc-800 text-zinc-400 border border-zinc-700 uppercase">
            {data.env}
          </span>
        </div>
        {data.cash && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
              <div className="text-xs uppercase tracking-wider text-zinc-500">
                Free cash
              </div>
              <div className="mt-1 text-lg font-semibold">
                {money(data.cash.free)}
              </div>
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
              <div className="text-xs uppercase tracking-wider text-zinc-500">
                Invested
              </div>
              <div className="mt-1 text-lg font-semibold">
                {money(data.cash.invested)}
              </div>
            </div>
            <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
              <div className="text-xs uppercase tracking-wider text-zinc-500">
                Total
              </div>
              <div className="mt-1 text-lg font-semibold">
                {money(data.cash.total)}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Positions */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-300 uppercase tracking-wider">
            Open positions
          </h2>
          <span className="text-xs text-zinc-500">
            {positions.length} position{positions.length === 1 ? "" : "s"}
          </span>
        </div>

        {positions.length === 0 ? (
          <div className="rounded-md border border-zinc-800 px-4 py-6 text-center text-sm text-zinc-500">
            No open positions in this account.
          </div>
        ) : (
          <>
            {addable.length > 0 && (
              <div className="flex flex-wrap items-center gap-3 rounded-md border border-zinc-800 bg-zinc-900 px-4 py-3">
                <span className="text-sm text-zinc-400">
                  {addable.length} US-listed holding
                  {addable.length === 1 ? " is" : "s are"} not on the
                  watchlist.
                </span>
                <button
                  onClick={addHoldings}
                  disabled={adding}
                  className="px-3 py-1.5 rounded-md bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm font-medium transition-colors"
                >
                  {adding ? "Adding…" : "Add holdings to watchlist"}
                </button>
                {addMsg && <span className="text-xs text-zinc-500">{addMsg}</span>}
              </div>
            )}
            {addable.length === 0 && addMsg && (
              <div className="rounded-md border border-zinc-800 bg-zinc-900 px-4 py-3 text-sm text-emerald-400">
                {addMsg} — every screenable holding is on the watchlist.
              </div>
            )}
            {nonUs.length > 0 && (
              <p className="text-xs text-zinc-600">
                {nonUs.length} non-US holding{nonUs.length === 1 ? "" : "s"}{" "}
                (e.g. London-listed ETFs) shown but not screened — the agent
                only analyses US equities.
              </p>
            )}
            <PositionsTable positions={positions} />
          </>
        )}
      </section>

      <div className="flex items-center gap-3">
        <button
          onClick={() => void load()}
          disabled={loading}
          className="px-4 py-2 rounded-md border border-zinc-700 text-sm text-zinc-300 hover:border-zinc-500 hover:text-zinc-100 disabled:opacity-40 transition-colors"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
        <span className="text-xs text-zinc-600">
          Updated {new Date(data.checkedAt).toLocaleString("en-GB")}
        </span>
      </div>
    </div>
  );
}

function PositionsTable({ positions }: { positions: PortfolioPosition[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-zinc-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wider text-zinc-500">
            <th className="px-4 py-2.5 font-medium">Symbol</th>
            <th className="px-4 py-2.5 font-medium text-right">Qty</th>
            <th className="px-4 py-2.5 font-medium text-right">Avg</th>
            <th className="px-4 py-2.5 font-medium text-right">Price</th>
            <th className="px-4 py-2.5 font-medium text-right">Value</th>
            <th className="px-4 py-2.5 font-medium text-right">P&amp;L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800">
          {positions.map((p) => (
            <tr key={p.ticker} className="bg-zinc-900">
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-bold text-zinc-100">
                    {p.symbol}
                  </span>
                  {p.inWatchlist ? (
                    <span className="text-xs rounded px-1.5 py-0.5 bg-emerald-900/50 text-emerald-400 border border-emerald-800">
                      watched
                    </span>
                  ) : p.usListed ? (
                    <span className="text-xs rounded px-1.5 py-0.5 bg-zinc-800 text-zinc-500 border border-zinc-700">
                      untracked
                    </span>
                  ) : (
                    <span className="text-xs rounded px-1.5 py-0.5 bg-zinc-900 text-zinc-600 border border-zinc-800">
                      not screened
                    </span>
                  )}
                </div>
              </td>
              <td className="px-4 py-3 text-right font-mono text-zinc-300">
                {p.quantity.toLocaleString("en-GB", {
                  maximumFractionDigits: 4,
                })}
              </td>
              <td className="px-4 py-3 text-right font-mono text-zinc-400">
                {money(p.averagePrice)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-zinc-300">
                {money(p.currentPrice)}
              </td>
              <td className="px-4 py-3 text-right font-mono text-zinc-100">
                {money(p.marketValue)}
              </td>
              <td className={`px-4 py-3 text-right font-mono ${pnlColor(p.pnl)}`}>
                <div>{signed(p.pnl)}</div>
                <div className="text-xs">{pct(p.pnlPct)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
