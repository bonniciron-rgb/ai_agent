"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { LlmUsageRow } from "@/app/api/llm-usage/route";

const PERIODS = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

const DailyCostChart = dynamic(() => import("./DailyCostChart"), { ssr: false });

interface Summary {
  totalCost: number;
  dailyAvg: number;
  cacheHitRate: number | null;
  callCount: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCacheReadTokens: number;
}

function summarise(rows: LlmUsageRow[], days: number): Summary {
  const totalCost = rows.reduce((s, r) => s + Number(r.total_cost_usd), 0);
  const totalInputTokens = rows.reduce((s, r) => s + r.total_input_tokens, 0);
  const totalOutputTokens = rows.reduce((s, r) => s + r.total_output_tokens, 0);
  const totalCacheReadTokens = rows.reduce((s, r) => s + r.total_cache_read_tokens, 0);
  const callCount = rows.reduce((s, r) => s + r.call_count, 0);
  const denom = totalCacheReadTokens + totalInputTokens;
  return {
    totalCost,
    dailyAvg: totalCost / days,
    cacheHitRate: denom > 0 ? totalCacheReadTokens / denom : null,
    callCount,
    totalInputTokens,
    totalOutputTokens,
    totalCacheReadTokens,
  };
}

interface PassRow {
  pass_type: string;
  model: string;
  cost: number;
  calls: number;
  input: number;
  output: number;
  cache_read: number;
}

function groupByPassAndModel(rows: LlmUsageRow[]): PassRow[] {
  const map = new Map<string, PassRow>();
  for (const r of rows) {
    const key = `${r.pass_type}::${r.model}`;
    const existing = map.get(key) ?? {
      pass_type: r.pass_type,
      model: r.model,
      cost: 0,
      calls: 0,
      input: 0,
      output: 0,
      cache_read: 0,
    };
    existing.cost += Number(r.total_cost_usd);
    existing.calls += r.call_count;
    existing.input += r.total_input_tokens;
    existing.output += r.total_output_tokens;
    existing.cache_read += r.total_cache_read_tokens;
    map.set(key, existing);
  }
  return [...map.values()].sort((a, b) => b.cost - a.cost);
}

function dailyTotals(rows: LlmUsageRow[]): { date: string; cost: number }[] {
  const map = new Map<string, number>();
  for (const r of rows) {
    map.set(r.occurred_on, (map.get(r.occurred_on) ?? 0) + Number(r.total_cost_usd));
  }
  return [...map.entries()]
    .map(([date, cost]) => ({ date, cost: Math.round(cost * 10000) / 10000 }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function formatUsd(n: number): string {
  return `$${n.toFixed(2)}`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toString();
}

const PASS_COLORS: Record<string, string> = {
  screening: "bg-sky-900 text-sky-200",
  decision: "bg-indigo-900 text-indigo-200",
  other: "bg-zinc-800 text-zinc-300",
};

function PassPill({ pass }: { pass: string }) {
  const cls = PASS_COLORS[pass] ?? "bg-zinc-800 text-zinc-300";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {pass}
    </span>
  );
}

export default function UsageClient() {
  const [days, setDays] = useState(30);
  const [rows, setRows] = useState<LlmUsageRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [schemaPending, setSchemaPending] = useState(false);
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    setSchemaPending(false);
    fetch(`/api/llm-usage?days=${days}`)
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (id !== requestId.current) return;
        if (!ok) throw new Error(d.error ?? "Failed to load");
        setRows(d.rows);
        setSchemaPending(Boolean(d.schemaPending));
        setLoading(false);
      })
      .catch((err) => {
        if (id !== requestId.current) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }, [days]);

  const summary = useMemo(() => summarise(rows, days), [rows, days]);
  const breakdown = useMemo(() => groupByPassAndModel(rows), [rows]);
  const daily = useMemo(() => dailyTotals(rows), [rows]);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">LLM Usage &amp; Cost</h1>
      <p className="mt-1 text-sm text-zinc-500">
        Anthropic API spend, cache efficiency, and pass-type breakdown.
      </p>

      {/* Period selector */}
      <div className="mt-6 flex gap-2">
        {PERIODS.map((p) => (
          <button
            key={p.days}
            onClick={() => setDays(p.days)}
            className={`rounded px-3 py-1.5 text-sm transition-colors ${
              days === p.days
                ? "bg-indigo-600 text-white"
                : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-100"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
          <p className="font-medium">Failed to load usage data</p>
          <p className="mt-1 font-mono text-xs text-rose-300/80">{error}</p>
        </div>
      )}

      {loading && !error && (
        <p className="mt-8 text-sm text-zinc-500">Loading…</p>
      )}

      {!loading && !error && rows.length === 0 && schemaPending && (
        <div className="mt-6 rounded-lg border border-amber-900 bg-amber-950/40 p-6 text-sm text-amber-200">
          <p className="font-medium">First-run pending</p>
          <p className="mt-1 text-amber-300/80">
            The <code className="font-mono">llmusage</code> table will be created
            automatically the next time the daily agent loop runs (06:30 UTC weekdays).
          </p>
        </div>
      )}

      {!loading && !error && rows.length === 0 && !schemaPending && (
        <div className="mt-6 rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
          No LLM usage recorded for the last {days} days. The agent populates the
          <code className="font-mono ml-1">llmusage</code> table on every API call.
        </div>
      )}

      {!loading && !error && rows.length > 0 && (
        <>
          {/* Summary cards */}
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Card label={`Total spend (${days}d)`} value={formatUsd(summary.totalCost)} />
            <Card label="Avg per day" value={formatUsd(summary.dailyAvg)} />
            <Card
              label="Cache hit rate"
              value={summary.cacheHitRate !== null ? `${(summary.cacheHitRate * 100).toFixed(1)}%` : "—"}
              tone={summary.cacheHitRate !== null && summary.cacheHitRate >= 0.5 ? "good" : undefined}
            />
            <Card label="API calls" value={summary.callCount.toLocaleString()} />
          </div>

          {/* Token breakdown */}
          <div className="mt-3 grid grid-cols-3 gap-3 text-xs text-zinc-500">
            <div>Input: {formatTokens(summary.totalInputTokens)}</div>
            <div>Output: {formatTokens(summary.totalOutputTokens)}</div>
            <div>Cache reads: {formatTokens(summary.totalCacheReadTokens)}</div>
          </div>

          {/* Daily cost chart */}
          <div className="mt-6 rounded-lg border border-zinc-800 overflow-hidden">
            <p className="px-4 py-2 text-xs text-zinc-500 bg-zinc-900/40 border-b border-zinc-800">
              Daily cost (USD)
            </p>
            <DailyCostChart data={daily} />
          </div>

          {/* Pass / model breakdown */}
          <div className="mt-6 rounded-lg border border-zinc-800 overflow-hidden">
            <p className="px-4 py-2 text-xs text-zinc-500 bg-zinc-900/40 border-b border-zinc-800">
              Breakdown by pass type and model
            </p>
            <table className="w-full text-sm">
              <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="px-4 py-2 text-left">Pass</th>
                  <th className="px-4 py-2 text-left">Model</th>
                  <th className="px-4 py-2 text-right">Calls</th>
                  <th className="px-4 py-2 text-right">Input tokens</th>
                  <th className="px-4 py-2 text-right">Output tokens</th>
                  <th className="px-4 py-2 text-right">Cache reads</th>
                  <th className="px-4 py-2 text-right">Cost (USD)</th>
                  <th className="px-4 py-2 text-right">% of total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {breakdown.map((b) => (
                  <tr key={`${b.pass_type}::${b.model}`} className="hover:bg-zinc-900/30">
                    <td className="px-4 py-2"><PassPill pass={b.pass_type} /></td>
                    <td className="px-4 py-2 font-mono text-xs text-zinc-400">{b.model}</td>
                    <td className="px-4 py-2 text-right font-mono">{b.calls.toLocaleString()}</td>
                    <td className="px-4 py-2 text-right font-mono">{formatTokens(b.input)}</td>
                    <td className="px-4 py-2 text-right font-mono">{formatTokens(b.output)}</td>
                    <td className="px-4 py-2 text-right font-mono">{formatTokens(b.cache_read)}</td>
                    <td className="px-4 py-2 text-right font-mono text-zinc-100">{formatUsd(b.cost)}</td>
                    <td className="px-4 py-2 text-right font-mono text-zinc-500">
                      {summary.totalCost > 0 ? `${((b.cost / summary.totalCost) * 100).toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}

function Card({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  const valueClass =
    tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : "text-zinc-100";
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className={`mt-1 text-xl font-semibold tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}
