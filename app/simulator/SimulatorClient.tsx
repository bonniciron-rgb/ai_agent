"use client";

import { useState, useTransition } from "react";
import dynamic from "next/dynamic";
import type { SimulatorBar, SimulatorProposal } from "@/lib/queries";

// Load chart component client-side only (uses canvas/DOM)
const SimulatorChart = dynamic(() => import("./SimulatorChart"), { ssr: false });

const PERIODS = [
  { label: "1 month", days: 30 },
  { label: "3 months", days: 90 },
  { label: "6 months", days: 180 },
  { label: "1 year", days: 365 },
  { label: "2 years", days: 730 },
];

interface Props {
  symbols: string[];
}

export default function SimulatorClient({ symbols }: Props) {
  const defaultSymbol = symbols[0] ?? "";
  const [symbol, setSymbol] = useState(defaultSymbol);
  const [days, setDays] = useState(180);
  const [capital, setCapital] = useState(10000);
  const [bars, setBars] = useState<SimulatorBar[]>([]);
  const [proposals, setProposals] = useState<SimulatorProposal[]>([]);
  const [ran, setRan] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function run() {
    if (!symbol) return;
    setError(null);
    startTransition(async () => {
      try {
        const res = await fetch(`/api/simulator?symbol=${encodeURIComponent(symbol)}&days=${days}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? res.statusText);
        setBars(data.bars);
        setProposals(data.proposals);
        setRan(true);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    });
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Simulator</h1>
      <p className="mt-1 text-sm text-zinc-500">
        Replay agent proposals on historical price data and compute hypothetical P&amp;L.
      </p>

      {/* Controls */}
      <div className="mt-6 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-zinc-500">Symbol</label>
          {symbols.length > 0 ? (
            <select
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          ) : (
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="AAPL"
              className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 w-28 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-zinc-500">Period</label>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            {PERIODS.map((p) => (
              <option key={p.days} value={p.days}>{p.label}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-zinc-500">Starting capital (£)</label>
          <input
            type="number"
            min={100}
            max={1000000}
            step={100}
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
            className="rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 w-32 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <button
          onClick={run}
          disabled={!symbol || isPending}
          className="rounded bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isPending ? "Running…" : "▶ Run"}
        </button>
      </div>

      {error && (
        <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
          <p className="font-medium">Simulation error</p>
          <p className="mt-1 font-mono text-xs text-rose-300/80">{error}</p>
        </div>
      )}

      {!ran && !isPending && !error && (
        <div className="mt-10 rounded-lg border border-zinc-800 p-8 text-center text-sm text-zinc-500">
          Select a symbol and period, then click <strong className="text-zinc-400">▶ Run</strong> to
          load the price chart with agent proposal markers and simulated equity curve.
        </div>
      )}

      {isPending && (
        <p className="mt-10 text-sm text-zinc-500">Loading data…</p>
      )}

      {ran && !isPending && (
        <div className="mt-8">
          <SimulatorChart
            bars={bars}
            proposals={proposals}
            initialCapital={capital}
          />

          {proposals.length === 0 && bars.length > 0 && (
            <p className="mt-4 text-sm text-zinc-500">
              No agent proposals found for {symbol} in this period — price chart shown without markers.
            </p>
          )}
        </div>
      )}
    </main>
  );
}
