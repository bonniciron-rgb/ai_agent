"use client";

import { useState } from "react";
import type { T212ConnectionResult } from "@/app/api/connection/t212/route";
import type { SyncResult } from "@/app/api/sync/route";

function num(v: number | undefined): string {
  if (v === undefined) return "—";
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
        ok ? "bg-emerald-900 text-emerald-200" : "bg-rose-900 text-rose-200"
      }`}
    >
      {label}
    </span>
  );
}

export default function ConnectionsClient() {
  const [t212, setT212] = useState<T212ConnectionResult | null>(null);
  const [t212Loading, setT212Loading] = useState(false);
  const [t212Err, setT212Err] = useState<string | null>(null);

  const [sync, setSync] = useState<SyncResult | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncErr, setSyncErr] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState(true);

  async function testT212() {
    setT212Loading(true);
    setT212Err(null);
    setT212(null);
    try {
      const res = await fetch("/api/connection/t212", { cache: "no-store" });
      if (!res.ok && res.status === 401) {
        setT212Err("Session expired — reload the page and sign in again.");
        return;
      }
      setT212((await res.json()) as T212ConnectionResult);
    } catch (e) {
      setT212Err(e instanceof Error ? e.message : String(e));
    } finally {
      setT212Loading(false);
    }
  }

  async function runSync() {
    setSyncLoading(true);
    setSyncErr(null);
    setSync(null);
    try {
      const res = await fetch("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dryRun }),
      });
      if (!res.ok && res.status === 401) {
        setSyncErr("Session expired — reload the page and sign in again.");
        return;
      }
      setSync((await res.json()) as SyncResult);
    } catch (e) {
      setSyncErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Connections</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Test the Trading 212 connection and trigger a data sync.
        </p>
      </div>

      {/* --- Trading 212 --- */}
      <section className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-200">Trading 212</h2>
          <button
            type="button"
            onClick={testT212}
            disabled={t212Loading}
            className="rounded border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
          >
            {t212Loading ? "Testing…" : "Test connection"}
          </button>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          Calls the T212 account endpoint with the dashboard&apos;s API key. Read-only.
        </p>

        {t212Err && (
          <p className="mt-3 text-sm text-rose-300">{t212Err}</p>
        )}

        {t212 && (
          <div className="mt-4 space-y-2">
            <div className="flex items-center gap-2">
              <StatusPill
                ok={t212.ok}
                label={
                  t212.ok
                    ? "Connected"
                    : t212.configured
                      ? "Failed"
                      : "Not configured"
                }
              />
              <span className="text-xs text-zinc-500">
                env: {t212.env}
                {t212.status ? ` · HTTP ${t212.status}` : ""}
              </span>
            </div>
            {t212.ok && (
              <dl className="grid grid-cols-3 gap-3 rounded bg-zinc-900 p-3 text-sm">
                <div>
                  <dt className="text-xs text-zinc-500">Free cash</dt>
                  <dd className="font-mono text-zinc-200">{num(t212.free)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-zinc-500">Invested</dt>
                  <dd className="font-mono text-zinc-200">{num(t212.invested)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-zinc-500">Total</dt>
                  <dd className="font-mono text-zinc-200">{num(t212.total)}</dd>
                </div>
              </dl>
            )}
            {t212.message && (
              <p
                className={`text-sm ${t212.ok ? "text-zinc-400" : "text-rose-300"}`}
              >
                {t212.message}
              </p>
            )}
            <p className="text-xs text-zinc-600">
              Checked {new Date(t212.checkedAt).toLocaleString()}
            </p>
          </div>
        )}
      </section>

      {/* --- Data sync --- */}
      <section className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-200">Data sync</h2>
          <button
            type="button"
            onClick={runSync}
            disabled={syncLoading}
            className="rounded border border-emerald-800 bg-emerald-900/60 px-3 py-1.5 text-sm text-emerald-100 hover:bg-emerald-900 disabled:opacity-50"
          >
            {syncLoading ? "Triggering…" : "Sync now"}
          </button>
        </div>
        <p className="mt-1 text-xs text-zinc-500">
          Runs the daily loop: ingests fresh prices, reads your live T212 portfolio,
          and runs the agent. Logs appear in GitHub Actions.
        </p>

        <label className="mt-3 flex items-center gap-2 text-sm text-zinc-400">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            className="accent-emerald-600"
          />
          Dry run — refresh data &amp; run the agent, but write nothing and send no
          Telegram (recommended)
        </label>

        {syncErr && <p className="mt-3 text-sm text-rose-300">{syncErr}</p>}

        {sync && (
          <div className="mt-4 space-y-2">
            <StatusPill
              ok={sync.ok}
              label={
                sync.ok ? "Triggered" : sync.configured ? "Failed" : "Not configured"
              }
            />
            <p className={`text-sm ${sync.ok ? "text-zinc-400" : "text-rose-300"}`}>
              {sync.message}
            </p>
            {sync.actionsUrl && (
              <a
                href={sync.actionsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block text-sm text-emerald-400 hover:underline"
              >
                Open GitHub Actions logs →
              </a>
            )}
          </div>
        )}
      </section>

      <p className="text-xs text-zinc-600">
        Both features read configuration from the dashboard&apos;s environment
        variables (Vercel), which are separate from the GitHub Actions secrets the
        cron jobs use. See <code className="font-mono">.env.example</code>.
      </p>
    </main>
  );
}
