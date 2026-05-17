import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getRedditBuzz, type BuzzTicker } from "@/lib/buzz";

export const dynamic = "force-dynamic";

export default async function BuzzPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const buzz = await getRedditBuzz();
  const rising = buzz.tickers.filter((t) => t.tier === "rising");

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Retail Buzz</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Most-discussed tickers across investing subreddits (r/wallstreetbets,
          r/stocks and others), aggregated by ApeWisdom. Low-traction tickers
          are dropped, the list is ranked by engagement-weighted buzz, and each
          ticker is classed by whether mentions are{" "}
          <span className="text-zinc-300">accelerating</span> vs 24h ago. A
          retail sentiment signal — momentum and awareness, not a buy
          recommendation.
        </p>

        <div className="mt-6">
          {buzz.error ? (
            <p className="rounded-lg border border-rose-900 bg-rose-950/40 p-4 text-sm text-rose-200">
              Could not load retail buzz: {buzz.error}
            </p>
          ) : buzz.tickers.length === 0 ? (
            <p className="rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
              No tickers cleared the buzz filters right now.
            </p>
          ) : (
            <>
              {rising.length > 0 && (
                <div className="mb-4 rounded-lg border border-teal-900 bg-teal-950/30 p-4 text-sm">
                  <span className="font-medium text-teal-300">
                    Accelerating:
                  </span>{" "}
                  <span className="text-zinc-300">
                    {rising.map((t) => t.ticker).join(", ")}
                  </span>
                  <span className="text-zinc-500">
                    {" "}
                    — buzz rising sharply vs 24h ago. A momentum cue worth a
                    look; confirm against technicals and the agent&apos;s own
                    analysis before acting.
                  </span>
                </div>
              )}
              <div className="overflow-hidden rounded-lg border border-zinc-800">
                <table className="w-full text-sm">
                  <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                    <tr>
                      <th className="px-4 py-2 text-left">#</th>
                      <th className="px-4 py-2 text-left">Ticker</th>
                      <th className="px-4 py-2 text-left">Company</th>
                      <th className="px-4 py-2 text-right">Mentions</th>
                      <th className="px-4 py-2 text-right">vs 24h</th>
                      <th className="px-4 py-2 text-left">Trend</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800">
                    {buzz.tickers.map((t, i) => (
                      <tr key={t.ticker} className="hover:bg-zinc-900/30">
                        <td className="px-4 py-2 text-zinc-600">{i + 1}</td>
                        <td className="px-4 py-2 font-mono font-bold text-zinc-100">
                          {t.ticker}
                        </td>
                        <td className="max-w-[16rem] truncate px-4 py-2 text-zinc-300">
                          {t.company}
                        </td>
                        <td className="px-4 py-2 text-right font-mono text-zinc-300">
                          {t.mentions.toLocaleString()}
                        </td>
                        <td
                          className={`px-4 py-2 text-right font-mono ${momentumColor(t)}`}
                        >
                          {momentumLabel(t)}
                        </td>
                        <td className="px-4 py-2">
                          <TrendBadge tier={t.tier} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </main>
    </>
  );
}

function momentumLabel(t: BuzzTicker): string {
  if (t.mentions24hAgo === 0) return "new";
  const p = Math.round(t.momentumPct * 100);
  return `${p >= 0 ? "+" : ""}${p}%`;
}

function momentumColor(t: BuzzTicker): string {
  if (t.mentions24hAgo === 0 || t.momentumPct >= 0.25)
    return "text-emerald-400";
  if (t.momentumPct <= -0.25) return "text-rose-400";
  return "text-zinc-400";
}

function TrendBadge({ tier }: { tier: BuzzTicker["tier"] }) {
  const map = {
    rising: "text-emerald-400",
    fading: "text-rose-400",
    steady: "text-zinc-500",
  } as const;
  const label = { rising: "Rising", fading: "Fading", steady: "Steady" }[tier];
  return <span className={`text-xs ${map[tier]}`}>{label}</span>;
}
