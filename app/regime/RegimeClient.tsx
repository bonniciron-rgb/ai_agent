"use client";

import { useEffect, useState } from "react";

interface RegimeRow {
  id: number;
  as_of: string;
  regime: string;
  spy_close: string;
  spy_sma_50: string;
  spy_sma_200: string;
  spy_above_200sma: boolean;
  spy_50_over_200sma: boolean;
  vix_close: string;
  vix_sma_20: string | null;
  notes_json: string;
  created_at: string;
}

interface ApiResponse {
  latest: RegimeRow | null;
  history: RegimeRow[];
}

const REGIME_COLORS: Record<string, { badge: string; cell: string }> = {
  bull: { badge: "bg-emerald-600 text-white", cell: "bg-emerald-700" },
  bear: { badge: "bg-rose-600 text-white", cell: "bg-rose-600" },
  crisis: { badge: "bg-red-700 text-white", cell: "bg-red-800" },
  correction: { badge: "bg-amber-500 text-zinc-900", cell: "bg-amber-500" },
  sideways: { badge: "bg-zinc-600 text-zinc-100", cell: "bg-zinc-600" },
  mixed: { badge: "bg-zinc-700 text-zinc-200", cell: "bg-zinc-700" },
};

function regimeBadgeClass(regime: string): string {
  return REGIME_COLORS[regime]?.badge ?? "bg-zinc-700 text-zinc-200";
}

function regimeCellClass(regime: string): string {
  return REGIME_COLORS[regime]?.cell ?? "bg-zinc-700";
}

function spyVs200(row: RegimeRow): string {
  const close = parseFloat(row.spy_close);
  const sma200 = parseFloat(row.spy_sma_200);
  if (!sma200) return "--";
  const pct = ((close - sma200) / sma200) * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

function vixVs20sma(row: RegimeRow): string {
  if (!row.vix_sma_20) return parseFloat(row.vix_close).toFixed(2);
  const close = parseFloat(row.vix_close);
  const sma20 = parseFloat(row.vix_sma_20);
  const pct = ((close - sma20) / sma20) * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${parseFloat(row.vix_close).toFixed(2)} (${sign}${pct.toFixed(1)}% vs 20d)`;
}

export function RegimeClient() {
  const [data, setData] = useState<ApiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/macro-regime")
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (!ok) throw new Error(d.error ?? "Failed to load");
        setData(d);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }, []);

  if (loading) {
    return <p className="mt-8 text-sm text-zinc-500">Loading...</p>;
  }

  if (error) {
    return (
      <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
        <p className="font-medium">Failed to load regime data</p>
        <p className="mt-1 font-mono text-xs text-rose-300/80">{error}</p>
      </div>
    );
  }

  if (!data?.latest) {
    return (
      <div className="mt-6 rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
        No regime data yet -- the daily cron will populate this after the next 22:30 UTC run.
      </div>
    );
  }

  const { latest, history } = data;
  const notes: string[] = (() => {
    try {
      return JSON.parse(latest.notes_json);
    } catch {
      return [];
    }
  })();

  return (
    <div className="space-y-6">
      {/* Regime badge */}
      <div className="flex flex-col items-start gap-2">
        <span
          className={`rounded-full px-6 py-2 text-2xl font-bold tracking-wide uppercase ${regimeBadgeClass(latest.regime)}`}
        >
          {latest.regime}
        </span>
        <p className="text-sm text-zinc-400">As of {latest.as_of}</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="SPY Close" value={`$${parseFloat(latest.spy_close).toFixed(2)}`} />
        <StatCard label="SPY vs 200d SMA" value={spyVs200(latest)} />
        <StatCard label="VIX" value={parseFloat(latest.vix_close).toFixed(2)} />
        <StatCard label="VIX vs 20d SMA" value={vixVs20sma(latest)} />
      </div>

      {/* Notes */}
      {notes.length > 0 && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3">
          <p className="text-xs text-zinc-500 mb-2">Classification rationale</p>
          <ul className="space-y-1">
            {notes.map((note, i) => (
              <li key={i} className="text-sm text-zinc-300 flex gap-2">
                <span className="text-zinc-600">-</span>
                <span>{note}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 30-day history strip */}
      {history.length > 0 && (
        <div>
          <div className="flex gap-1 flex-wrap">
            {history.map((row) => (
              <div
                key={row.as_of}
                className={`relative h-8 w-8 rounded group cursor-default ${regimeCellClass(row.regime)}`}
                title={`${row.as_of}: ${row.regime}`}
              >
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10 whitespace-nowrap rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-100 border border-zinc-700">
                  {row.as_of}: {row.regime}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-zinc-500">Last 30 days</p>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-zinc-100">{value}</p>
    </div>
  );
}
