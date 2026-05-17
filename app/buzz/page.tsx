import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getRedditBuzz } from "@/lib/reddit";

export const dynamic = "force-dynamic";

export default async function BuzzPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const buzz = await getRedditBuzz();
  const strong = buzz.tickers.filter((t) => t.tier === "strong");

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Retail Buzz</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Most-discussed tickers on r/wallstreetbets, r/stocks and r/StockMarket
          — noise-filtered: validated against the SEC ticker list, slang
          dropped, one-off mentions discarded, and ranked by engagement (upvotes
          + comments), not raw count. This is a retail
          <span className="text-zinc-300"> sentiment</span> signal — momentum
          and awareness, not a buy recommendation.
        </p>

        <div className="mt-6">
          {buzz.error ? (
            <p className="rounded-lg border border-rose-900 bg-rose-950/40 p-4 text-sm text-rose-200">
              Could not load Reddit buzz: {buzz.error}
            </p>
          ) : buzz.tickers.length === 0 ? (
            <p className="rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
              No ticker cleared the noise filters across {buzz.postsScanned}{" "}
              scanned posts.
            </p>
          ) : (
            <>
              {strong.length > 0 && (
                <div className="mb-4 rounded-lg border border-teal-900 bg-teal-950/30 p-4 text-sm">
                  <span className="font-medium text-teal-300">
                    Worth a look:
                  </span>{" "}
                  <span className="text-zinc-300">
                    {strong.map((t) => t.ticker).join(", ")}
                  </span>
                  <span className="text-zinc-500">
                    {" "}
                    — strongest filtered buzz right now. Confirm against
                    technicals and the agent&apos;s own analysis before acting.
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
                      <th className="px-4 py-2 text-right">Buzz</th>
                      <th className="px-4 py-2 text-left">Signal</th>
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
                          {t.mentions}
                        </td>
                        <td className="px-4 py-2 text-right font-mono text-zinc-300">
                          {t.buzzScore.toFixed(1)}
                        </td>
                        <td className="px-4 py-2">
                          <span
                            className={
                              t.tier === "strong"
                                ? "text-teal-400"
                                : "text-zinc-500"
                            }
                          >
                            {t.tier === "strong" ? "Strong" : "Moderate"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-zinc-600">
                Scanned {buzz.postsScanned} hot posts. Refreshed every 6h.
              </p>
            </>
          )}
        </div>
      </main>
    </>
  );
}
