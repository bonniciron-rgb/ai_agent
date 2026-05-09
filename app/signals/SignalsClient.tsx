"use client";

import { useState } from "react";

interface Channel {
  id: number;
  handle: string;
  paused: boolean;
  added_at: string;
  last_run_at: string | null;
  signal_count_7d: number;
}

const V2_SOURCES = [
  { name: "Reddit (r/wallstreetbets)", description: "Retail sentiment & momentum plays" },
  { name: "Twitter/X sentiment", description: "Real-time ticker mentions & crowd mood" },
  { name: "Options flow", description: "Unusual options activity & dark pool prints" },
  { name: "Insider trades (Form 4)", description: "SEC Form 4 executive buy/sell filings" },
  { name: "Congressional trades", description: "STOCK Act disclosures — congress member trades" },
  { name: "13F hedge fund holdings", description: "Quarterly institutional position changes" },
  { name: "Short interest", description: "Days-to-cover & borrow rate for squeeze detection" },
  { name: "ARK holdings", description: "Cathie Wood daily buy/sell basket changes" },
];

export function SignalsClient({ initial }: { initial: Channel[] }) {
  const [channels, setChannels] = useState<Channel[]>(initial);
  const [newHandle, setNewHandle] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    const res = await fetch("/api/signals/channels");
    if (res.ok) setChannels(await res.json());
  }

  async function addChannel() {
    if (!newHandle.trim()) return;
    setAdding(true);
    setError(null);
    try {
      const res = await fetch("/api/signals/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handle: newHandle.trim() }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error ?? "Failed to add channel"); return; }
      setNewHandle("");
      await reload();
    } finally {
      setAdding(false);
    }
  }

  async function togglePaused(ch: Channel) {
    const res = await fetch(`/api/signals/channels/${ch.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paused: !ch.paused }),
    });
    if (res.ok) await reload();
  }

  async function removeChannel(ch: Channel) {
    if (!confirm(`Remove ${ch.handle}? This cannot be undone.`)) return;
    const res = await fetch(`/api/signals/channels/${ch.id}`, { method: "DELETE" });
    if (res.ok) await reload();
  }

  return (
    <div className="space-y-10">
      {/* Active channels */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-300 uppercase tracking-wider">
            Active channels
          </h2>
          <span className="text-xs text-zinc-500">
            {channels.filter((c) => !c.paused).length} active / {channels.length} total
          </span>
        </div>

        {error && (
          <div className="rounded-md bg-rose-950 border border-rose-800 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        {channels.length === 0 ? (
          <div className="rounded-md border border-zinc-800 px-4 py-6 text-center text-sm text-zinc-500">
            No channels configured yet. Add one below.
          </div>
        ) : (
          <div className="divide-y divide-zinc-800 rounded-md border border-zinc-800 overflow-hidden">
            {channels.map((ch) => (
              <div
                key={ch.id}
                className={`flex items-center justify-between px-4 py-3 ${
                  ch.paused ? "bg-zinc-900/40" : "bg-zinc-900"
                }`}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`font-mono text-sm ${ch.paused ? "text-zinc-500" : "text-zinc-100"}`}>
                      {ch.handle}
                    </span>
                    {ch.paused && (
                      <span className="text-xs rounded px-1.5 py-0.5 bg-yellow-900/60 text-yellow-400 border border-yellow-800">
                        paused
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-zinc-500">
                    {ch.signal_count_7d} signals last 7d
                    {ch.last_run_at && ` · last run ${new Date(ch.last_run_at).toLocaleDateString()}`}
                  </div>
                </div>
                <div className="flex items-center gap-2 ml-4 shrink-0">
                  <button
                    onClick={() => togglePaused(ch)}
                    className="text-xs px-2.5 py-1 rounded border border-zinc-700 text-zinc-400 hover:text-zinc-100 hover:border-zinc-500 transition-colors"
                  >
                    {ch.paused ? "Resume" : "Pause"}
                  </button>
                  <button
                    onClick={() => removeChannel(ch)}
                    className="text-xs px-2.5 py-1 rounded border border-zinc-800 text-zinc-600 hover:text-rose-400 hover:border-rose-800 transition-colors"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Add channel */}
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="@ChannelName"
            value={newHandle}
            onChange={(e) => setNewHandle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addChannel()}
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-zinc-500"
          />
          <button
            onClick={addChannel}
            disabled={adding || !newHandle.trim()}
            className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm font-medium transition-colors"
          >
            {adding ? "Adding…" : "Add channel"}
          </button>
        </div>
      </section>

      {/* V2 sources */}
      <section className="space-y-4">
        <div>
          <h2 className="text-sm font-medium text-zinc-300 uppercase tracking-wider">
            Coming in V2
          </h2>
          <p className="mt-1 text-xs text-zinc-500">Planned signal sources — not yet implemented.</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {V2_SOURCES.map((src) => (
            <div key={src.name} className="rounded-md border border-zinc-800 bg-zinc-900/30 px-4 py-3">
              <div className="text-sm font-medium text-zinc-400">{src.name}</div>
              <div className="mt-0.5 text-xs text-zinc-600">{src.description}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
