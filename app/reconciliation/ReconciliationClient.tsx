"use client";

import { useEffect, useState } from "react";
import type { ReconciliationRow } from "@/app/api/reconciliation/route";

const STATUS_COLORS: Record<string, string> = {
  ok: "bg-emerald-900 text-emerald-200",
  drift_detected: "bg-amber-900 text-amber-200",
  error: "bg-rose-900 text-rose-200",
};

function StatusPill({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "bg-zinc-800 text-zinc-300";
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function JsonDetails({ json }: { json: string | null }) {
  if (!json) return <p className="text-zinc-500 text-sm">No details.</p>;
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return <pre className="text-xs text-rose-300">{json}</pre>;
  }
  return (
    <pre className="text-xs text-zinc-300 bg-zinc-900 rounded p-3 overflow-x-auto whitespace-pre-wrap">
      {JSON.stringify(parsed, null, 2)}
    </pre>
  );
}

export default function ReconciliationClient() {
  const [rows, setRows] = useState<ReconciliationRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [setupRequired, setSetupRequired] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    fetch("/api/reconciliation")
      .then((r) => {
        if (!r.ok) return r.json().then((d) => Promise.reject(d.error ?? r.statusText));
        return r.json();
      })
      .then((data) => {
        if (data && "setup_required" in data) {
          setSetupRequired(true);
        } else {
          setRows(data as ReconciliationRow[]);
        }
        setLoading(false);
      })
      .catch((err) => {
        setError(String(err));
        setLoading(false);
      });
  }, []);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Reconciliation</h1>
      <p className="mt-1 text-sm text-zinc-500">
        Nightly runs comparing DB state with T212. Click a row to see details.
      </p>

      {loading && (
        <p className="mt-8 text-sm text-zinc-500">Loading…</p>
      )}

      {error && (
        <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
          <p className="font-medium">Failed to load reconciliation data</p>
          <p className="mt-1 font-mono text-xs text-rose-300/80">{error}</p>
        </div>
      )}

      {setupRequired && (
        <div className="mt-6 rounded-lg border border-amber-800 bg-amber-950/40 p-4 text-sm text-amber-200">
          <p className="font-medium">Database table not initialised</p>
          <p className="mt-1 text-amber-300/80">
            The <code className="font-mono">reconciliation</code> table does not exist yet.
            Go to <strong>GitHub → Actions → init-db → Run workflow</strong> to create it,
            then reload this page.
          </p>
        </div>
      )}

      {!loading && !error && !setupRequired && rows.length === 0 && (
        <div className="mt-6 rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
          No reconciliation runs yet. The nightly job runs at 21:00 UTC on weekdays.
        </div>
      )}

      {!loading && !error && !setupRequired && rows.length > 0 && (
        <div className="mt-6 overflow-hidden rounded-lg border border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="px-4 py-2 text-left">Run at</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-right">Position drifts</th>
                <th className="px-4 py-2 text-right">Order drifts</th>
                <th className="px-4 py-2 text-left"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {rows.map((row) => (
                <>
                  <tr
                    key={row.id}
                    className="hover:bg-zinc-900/30 cursor-pointer"
                    onClick={() =>
                      setExpanded(expanded === row.id ? null : row.id)
                    }
                  >
                    <td className="px-4 py-2 text-zinc-400 font-mono text-xs">
                      {formatDate(row.run_at)}
                    </td>
                    <td className="px-4 py-2">
                      <StatusPill status={row.status} />
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {row.position_drifts === 0 ? (
                        <span className="text-zinc-600">0</span>
                      ) : (
                        <span className="text-amber-400">{row.position_drifts}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {row.order_drifts === 0 ? (
                        <span className="text-zinc-600">0</span>
                      ) : (
                        <span className="text-amber-400">{row.order_drifts}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-zinc-500 text-xs">
                      {expanded === row.id ? "▲ collapse" : "▼ expand"}
                    </td>
                  </tr>
                  {expanded === row.id && (
                    <tr key={`${row.id}-details`}>
                      <td
                        colSpan={5}
                        className="px-4 py-3 bg-zinc-900/60"
                      >
                        <JsonDetails json={row.details} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
