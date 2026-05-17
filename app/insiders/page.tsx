import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getInsiderActivity } from "@/lib/insiders";

export const dynamic = "force-dynamic";

export default async function InsidersPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const activity = await getInsiderActivity();

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">
          Insider Activity
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Recent insider buys and sells (SEC Form 4) for the active watchlist,
          last 90 days, from Finnhub. An open-market purchase by an insider is a
          notable conviction signal.
        </p>

        <div className="mt-6">
          {!activity.configured ? (
            <p className="rounded-lg border border-amber-900 bg-amber-950/40 p-4 text-sm text-amber-200">
              FINNHUB_API_KEY is not configured in this environment — insider
              activity can&apos;t be loaded.
            </p>
          ) : activity.txns.length === 0 ? (
            <p className="rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
              No insider buys or sells in the last 90 days
              {activity.error ? ` (${activity.error})` : ""}.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-zinc-800">
              <table className="w-full text-sm">
                <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-4 py-2 text-left">Date</th>
                    <th className="px-4 py-2 text-left">Symbol</th>
                    <th className="px-4 py-2 text-left">Insider</th>
                    <th className="px-4 py-2 text-left">Type</th>
                    <th className="px-4 py-2 text-right">Shares</th>
                    <th className="px-4 py-2 text-right">Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {activity.txns.map((t, i) => (
                    <tr
                      key={`${t.symbol}-${t.name}-${t.date}-${i}`}
                      className="hover:bg-zinc-900/30"
                    >
                      <td className="px-4 py-2 font-mono text-zinc-400">
                        {t.date || "—"}
                      </td>
                      <td className="px-4 py-2 font-mono font-bold text-zinc-100">
                        {t.symbol}
                      </td>
                      <td className="max-w-[16rem] truncate px-4 py-2 text-zinc-300">
                        {t.name}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={
                            t.isBuy ? "text-emerald-400" : "text-rose-400"
                          }
                        >
                          {t.label}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-zinc-300">
                        {t.shares.toLocaleString()}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-zinc-300">
                        {money(t.value)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </>
  );
}

/** Compact USD formatting: $75.3M, $1.2M, $340K. */
function money(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}
