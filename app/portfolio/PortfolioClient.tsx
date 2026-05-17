"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  PortfolioPosition,
  PortfolioResult,
  ValueChange,
} from "@/app/api/portfolio/route";

// Distinct slice colours for the value-distribution donut.
const PALETTE = [
  "#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444",
  "#a855f7", "#ec4899", "#14b8a6", "#84cc16", "#f97316",
];

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
          <div className="space-y-3">
            {/* Total value headline + 1d/7d change */}
            <div className="rounded-md border border-zinc-800 bg-zinc-900 p-5">
              <div className="text-xs uppercase tracking-wider text-zinc-500">
                Total value
              </div>
              <div className="mt-1 text-3xl font-semibold">
                {money(data.cash.total)}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-4 text-sm">
                {data.valueChange?.d1 || data.valueChange?.d7 ? (
                  <>
                    <DeltaPill label="1d" change={data.valueChange?.d1 ?? null} />
                    <DeltaPill label="7d" change={data.valueChange?.d7 ?? null} />
                  </>
                ) : (
                  <span className="text-xs text-zinc-600">
                    Daily value tracking has started — 1d / 7d changes appear
                    as history builds.
                  </span>
                )}
              </div>
            </div>
            {/* Stat cards */}
            <div className="grid grid-cols-3 gap-3">
              <StatCard label="Free cash" value={money(data.cash.free)} />
              <StatCard label="Invested" value={money(data.cash.invested)} />
              <StatCard
                label="Holdings"
                value={`${positions.length} ticker${
                  positions.length === 1 ? "" : "s"
                }`}
              />
            </div>
          </div>
        )}
        {/* Value distribution */}
        {data.cash && positions.length > 0 && (
          <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
            <div className="text-xs uppercase tracking-wider text-zinc-500">
              Value distribution
            </div>
            <div className="mt-3">
              <DonutChart positions={positions} freeCash={data.cash.free} />
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

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
      <div className="text-xs uppercase tracking-wider text-zinc-500">
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function DeltaPill({
  label,
  change,
}: {
  label: string;
  change: ValueChange | null;
}) {
  if (!change) {
    return <span className="text-zinc-600">{label} —</span>;
  }
  return (
    <span className={pnlColor(change.abs)}>
      <span className="text-zinc-500">{label}</span> {signed(change.abs)} (
      {pct(change.pct)})
    </span>
  );
}

function DonutChart({
  positions,
  freeCash,
}: {
  positions: PortfolioPosition[];
  freeCash: number;
}) {
  type Slice = { label: string; value: number; color: string };
  const sorted = positions
    .filter((p) => p.marketValue > 0)
    .sort((a, b) => b.marketValue - a.marketValue);
  const TOP = 8;
  const slices: Slice[] = sorted.slice(0, TOP).map((p, i) => ({
    label: p.symbol,
    value: p.marketValue,
    color: PALETTE[i % PALETTE.length],
  }));
  const rest = sorted.slice(TOP);
  if (rest.length > 0) {
    slices.push({
      label: `Other (${rest.length})`,
      value: rest.reduce((s, p) => s + p.marketValue, 0),
      color: "#71717a",
    });
  }
  if (freeCash > 0) {
    slices.push({ label: "Cash", value: freeCash, color: "#3f3f46" });
  }

  const total = slices.reduce((s, x) => s + x.value, 0);
  if (total <= 0) {
    return <p className="text-sm text-zinc-500">No value to chart.</p>;
  }

  const R = 60;
  const C = 2 * Math.PI * R;
  let offset = 0;

  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg width="160" height="160" viewBox="0 0 160 160" className="shrink-0">
        <g transform="rotate(-90 80 80)">
          {slices.map((s) => {
            const len = (s.value / total) * C;
            const el = (
              <circle
                key={s.label}
                cx="80"
                cy="80"
                r={R}
                fill="none"
                stroke={s.color}
                strokeWidth="22"
                strokeDasharray={`${len} ${C - len}`}
                strokeDashoffset={-offset}
              />
            );
            offset += len;
            return el;
          })}
        </g>
      </svg>
      <ul className="space-y-1 text-sm">
        {slices.map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span
              className="inline-block h-3 w-3 rounded-sm shrink-0"
              style={{ backgroundColor: s.color }}
            />
            <span className="font-mono text-zinc-300">{s.label}</span>
            <span className="text-zinc-500">
              {money(s.value)} · {((s.value / total) * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
