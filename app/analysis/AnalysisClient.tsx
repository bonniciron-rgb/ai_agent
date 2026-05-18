"use client";

import { useEffect, useState } from "react";
import type { DailyAnalysisRow } from "@/app/api/analysis/route";

function formatDate(ymd: string): string {
  // ymd is "YYYY-MM-DD"; render as a friendly date without TZ surprises.
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1)).toLocaleDateString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function OutcomePill({ row }: { row: DailyAnalysisRow }) {
  if (row.proposals_passed_risk > 0) {
    return (
      <span className="inline-block rounded px-2 py-0.5 text-xs font-medium bg-emerald-900 text-emerald-200">
        {row.proposals_passed_risk} proposal{row.proposals_passed_risk === 1 ? "" : "s"}
      </span>
    );
  }
  return (
    <span className="inline-block rounded px-2 py-0.5 text-xs font-medium bg-zinc-800 text-zinc-300">
      no trade
    </span>
  );
}

export default function AnalysisClient() {
  const [rows, setRows] = useState<DailyAnalysisRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [setupRequired, setSetupRequired] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    fetch("/api/analysis")
      .then((r) => {
        if (!r.ok) return r.json().then((d) => Promise.reject(d.error ?? r.statusText));
        return r.json();
      })
      .then((data) => {
        if (data && "setup_required" in data) {
          setSetupRequired(true);
        } else {
          const list = data as DailyAnalysisRow[];
          setRows(list);
          if (list.length > 0) setExpanded(list[0].id);
        }
        setLoading(false);
      })
      .catch((err) => {
        setError(String(err));
        setLoading(false);
      });
  }, []);

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Daily analysis</h1>
      <p className="mt-1 text-sm text-zinc-500">
        What the agent considered each day and why it did — or did not — propose a trade.
      </p>

      {loading && <p className="mt-8 text-sm text-zinc-500">Loading…</p>}

      {error && (
        <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
          <p className="font-medium">Failed to load analysis history</p>
          <p className="mt-1 font-mono text-xs text-rose-300/80">{error}</p>
        </div>
      )}

      {setupRequired && (
        <div className="mt-6 rounded-lg border border-amber-800 bg-amber-950/40 p-4 text-sm text-amber-200">
          <p className="font-medium">Database table not initialised</p>
          <p className="mt-1 text-amber-300/80">
            The <code className="font-mono">dailyanalysis</code> table does not exist yet. Go to{" "}
            <strong>GitHub → Actions → init-db → Run workflow</strong> to create it, then reload.
          </p>
        </div>
      )}

      {!loading && !error && !setupRequired && rows.length === 0 && (
        <div className="mt-6 rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
          No analysis recorded yet. The daily loop writes one row per run.
        </div>
      )}

      {!loading && !error && !setupRequired && rows.length > 0 && (
        <div className="mt-6 space-y-3">
          {rows.map((row) => {
            const open = expanded === row.id;
            return (
              <div key={row.id} className="rounded-lg border border-zinc-800 bg-zinc-900/30">
                <button
                  type="button"
                  className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-zinc-900/50"
                  onClick={() => setExpanded(open ? null : row.id)}
                >
                  <span className="flex items-center gap-3">
                    <span className="font-medium text-zinc-200">{formatDate(row.as_of)}</span>
                    <OutcomePill row={row} />
                  </span>
                  <span className="text-xs text-zinc-500">
                    {row.proposals_generated} proposed · {row.proposals_blocked_risk} risk-blocked
                    {" · "}
                    {open ? "▲" : "▼"}
                  </span>
                </button>
                {open && (
                  <div className="border-t border-zinc-800 px-4 py-3 space-y-3">
                    <div>
                      <h3 className="text-xs uppercase tracking-wider text-zinc-500">
                        Agent reasoning
                      </h3>
                      <p className="mt-1 whitespace-pre-wrap text-sm text-zinc-300">
                        {row.summary?.trim() || "(no reasoning text recorded)"}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-500">
                      <span>Symbols considered: {row.symbols_considered.join(", ") || "—"}</span>
                      <span>Agent iterations: {row.agent_iterations}</span>
                      <span>Model: {row.model}</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
