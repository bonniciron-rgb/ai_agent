"use client";

import { useEffect, useState } from "react";

interface Ticker {
  id: number;
  symbol: string;
  sector: string | null;
  notes: string | null;
  tags_json: string;
  paused: boolean;
  added_at: string;
  updated_at: string;
}

function parseTags(tags_json: string): string[] {
  try {
    return JSON.parse(tags_json) as string[];
  } catch {
    return [];
  }
}

function groupBySector(tickers: Ticker[]): [string, Ticker[]][] {
  const groups = new Map<string, Ticker[]>();
  for (const t of tickers) {
    const key = t.sector ?? "uncategorised";
    const arr = groups.get(key) ?? [];
    arr.push(t);
    groups.set(key, arr);
  }
  return [...groups.entries()].sort(([a], [b]) =>
    a === "uncategorised" ? 1 : b === "uncategorised" ? -1 : a.localeCompare(b),
  );
}

export function WatchlistClient() {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newSymbol, setNewSymbol] = useState("");
  const [newSector, setNewSector] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [newTags, setNewTags] = useState("");
  const [adding, setAdding] = useState(false);

  async function reload() {
    const res = await fetch("/api/watchlist");
    if (res.ok) {
      setTickers(await res.json());
    }
  }

  useEffect(() => {
    fetch("/api/watchlist")
      .then((r) => r.json())
      .then((data) => setTickers(data))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  async function addTicker() {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;
    setAdding(true);
    setError(null);
    try {
      const tags = newTags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: sym,
          sector: newSector.trim() || null,
          notes: newNotes.trim() || null,
          tags,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? "Failed to add ticker");
        return;
      }
      setNewSymbol("");
      setNewSector("");
      setNewNotes("");
      setNewTags("");
      await reload();
    } finally {
      setAdding(false);
    }
  }

  async function togglePaused(t: Ticker) {
    setError(null);
    const res = await fetch(`/api/watchlist/${t.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paused: !t.paused }),
    });
    if (res.ok) {
      await reload();
    } else {
      const data = await res.json().catch(() => ({}));
      setError((data as { error?: string }).error ?? "Failed to update ticker");
    }
  }

  async function deleteTicker(t: Ticker) {
    if (!window.confirm(`Remove ${t.symbol} from watchlist?`)) return;
    setError(null);
    const res = await fetch(`/api/watchlist/${t.id}`, { method: "DELETE" });
    if (res.ok || res.status === 204) {
      await reload();
    } else {
      const data = await res.json().catch(() => ({}));
      setError((data as { error?: string }).error ?? "Failed to delete ticker");
    }
  }

  const groups = groupBySector(tickers);
  const activeCount = tickers.filter((t) => !t.paused).length;

  return (
    <div className="space-y-8">
      {error && (
        <div className="rounded-md bg-rose-950 border border-rose-800 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {/* Add ticker form */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-zinc-300 uppercase tracking-wider">Add ticker</h2>
        <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4 space-y-3">
          <div className="flex flex-wrap gap-2">
            <input
              type="text"
              placeholder="Symbol (required)"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addTicker()}
              className="w-36 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500 font-mono uppercase"
            />
            <input
              type="text"
              placeholder="Sector (optional)"
              value={newSector}
              onChange={(e) => setNewSector(e.target.value)}
              className="flex-1 min-w-32 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
            />
            <input
              type="text"
              placeholder="Notes (optional)"
              value={newNotes}
              onChange={(e) => setNewNotes(e.target.value)}
              className="flex-1 min-w-40 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
            />
            <input
              type="text"
              placeholder="Tags (comma-separated)"
              value={newTags}
              onChange={(e) => setNewTags(e.target.value)}
              className="flex-1 min-w-40 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
            />
            <button
              onClick={addTicker}
              disabled={adding || !newSymbol.trim()}
              className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm font-medium transition-colors"
            >
              {adding ? "Adding…" : "Add ticker"}
            </button>
          </div>
        </div>
      </section>

      {/* Ticker list */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-300 uppercase tracking-wider">Tickers</h2>
          {!loading && (
            <span className="text-xs text-zinc-500">
              {activeCount} active / {tickers.length} total
            </span>
          )}
        </div>

        {loading ? (
          <div className="rounded-md border border-zinc-800 px-4 py-6 text-center text-sm text-zinc-500">
            Loading…
          </div>
        ) : tickers.length === 0 ? (
          <div className="rounded-md border border-zinc-800 px-4 py-6 text-center text-sm text-zinc-500">
            No tickers configured yet. Add one above.
          </div>
        ) : (
          <div className="space-y-6">
            {groups.map(([sector, items]) => (
              <div key={sector}>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
                  {sector.replace(/_/g, " ")}
                </h3>
                <div className="divide-y divide-zinc-800 rounded-md border border-zinc-800 overflow-hidden">
                  {items.map((t) => {
                    const tags = parseTags(t.tags_json);
                    return (
                      <div
                        key={t.id}
                        className={`flex items-center justify-between px-4 py-3 ${
                          t.paused ? "bg-zinc-900/40" : "bg-zinc-900"
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span
                              className={`font-mono font-bold text-sm ${
                                t.paused ? "text-zinc-500" : "text-zinc-100"
                              }`}
                            >
                              {t.symbol}
                            </span>
                            {t.sector && (
                              <span className="text-xs rounded px-1.5 py-0.5 bg-zinc-800 text-zinc-400 border border-zinc-700">
                                {t.sector.replace(/_/g, " ")}
                              </span>
                            )}
                            {t.paused && (
                              <span className="text-xs rounded px-1.5 py-0.5 bg-yellow-900/60 text-yellow-400 border border-yellow-800">
                                paused
                              </span>
                            )}
                            {tags.map((tag) => (
                              <span
                                key={tag}
                                className="text-xs rounded px-1.5 py-0.5 bg-zinc-800 text-zinc-500"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                          {t.notes && (
                            <p className="mt-0.5 text-xs italic text-zinc-500">{t.notes}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-2 ml-4 shrink-0">
                          <button
                            onClick={() => togglePaused(t)}
                            className="text-xs px-2.5 py-1 rounded border border-zinc-700 text-zinc-400 hover:text-zinc-100 hover:border-zinc-500 transition-colors"
                          >
                            {t.paused ? "Resume" : "Pause"}
                          </button>
                          <button
                            onClick={() => deleteTicker(t)}
                            className="text-xs px-2.5 py-1 rounded border border-zinc-800 text-zinc-600 hover:text-rose-400 hover:border-rose-800 transition-colors"
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
