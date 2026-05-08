import fs from "fs";
import path from "path";
import yaml from "js-yaml";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";

interface WatchlistEntry {
  symbol: string;
  sector?: string;
  notes?: string;
  tags?: string[];
}

interface WatchlistFile {
  entries?: WatchlistEntry[];
}

function loadWatchlist(): {
  entries: WatchlistEntry[];
  error: string | null;
} {
  const file = path.join(process.cwd(), "config", "watchlist.yaml");
  try {
    const raw = fs.readFileSync(file, "utf8");
    const parsed = yaml.load(raw) as WatchlistFile | null;
    return { entries: parsed?.entries ?? [], error: null };
  } catch (e) {
    return { entries: [], error: String(e) };
  }
}

export default async function WatchlistPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const { entries, error } = loadWatchlist();

  // Group by sector (uncategorised at the bottom).
  const groups = new Map<string, WatchlistEntry[]>();
  for (const e of entries) {
    const key = e.sector ?? "uncategorised";
    const arr = groups.get(key) ?? [];
    arr.push(e);
    groups.set(key, arr);
  }
  const sortedGroups = [...groups.entries()].sort(([a], [b]) =>
    a === "uncategorised" ? 1 : b === "uncategorised" ? -1 : a.localeCompare(b),
  );

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Watchlist</h1>

        {error ? (
          <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
            <p className="font-medium">Could not read watchlist.yaml</p>
            <p className="mt-1 font-mono text-xs text-rose-300/80">{error}</p>
          </div>
        ) : entries.length === 0 ? (
          <p className="mt-6 text-sm text-zinc-500">
            Watchlist is empty. Add entries to{" "}
            <code>config/watchlist.yaml</code>.
          </p>
        ) : (
          <div className="mt-6 space-y-8">
            {sortedGroups.map(([sector, items]) => (
              <section key={sector}>
                <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
                  {sector.replace(/_/g, " ")}
                </h2>
                <div className="overflow-hidden rounded-lg border border-zinc-800">
                  <table className="w-full text-sm">
                    <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                      <tr>
                        <th className="px-4 py-2 text-left">Symbol</th>
                        <th className="px-4 py-2 text-left">Sector</th>
                        <th className="px-4 py-2 text-left">Tags</th>
                        <th className="px-4 py-2 text-left">Notes</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800">
                      {items.map((e) => (
                        <tr key={e.symbol} className="hover:bg-zinc-900/30">
                          <td className="px-4 py-2 font-mono">{e.symbol}</td>
                          <td className="px-4 py-2 text-zinc-400">
                            {e.sector ?? "—"}
                          </td>
                          <td className="px-4 py-2">
                            {e.tags && e.tags.length > 0 ? (
                              <span className="flex flex-wrap gap-1">
                                {e.tags.map((t) => (
                                  <span
                                    key={t}
                                    className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-300"
                                  >
                                    {t}
                                  </span>
                                ))}
                              </span>
                            ) : (
                              <span className="text-zinc-600">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-zinc-400">
                            {e.notes ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        )}

        <p className="mt-10 text-xs text-zinc-500">
          Edit <code>config/watchlist.yaml</code> in the repo to change this
          list.
        </p>
      </main>
    </>
  );
}
