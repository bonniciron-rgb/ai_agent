import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getIpoCalendar, type Ipo } from "@/lib/ipos";

export const dynamic = "force-dynamic";

export default async function IposPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const cal = await getIpoCalendar();
  const today = new Date().toISOString().slice(0, 10);

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">IPO Calendar</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Recent and upcoming US IPOs — emerging companies entering the market,
          from Finnhub. Window: 30 days back to 60 days ahead.
        </p>

        <div className="mt-6">
          {!cal.configured ? (
            <p className="rounded-lg border border-amber-900 bg-amber-950/40 p-4 text-sm text-amber-200">
              FINNHUB_API_KEY is not configured in this environment — the IPO
              calendar can&apos;t be loaded.
            </p>
          ) : cal.error ? (
            <p className="rounded-lg border border-rose-900 bg-rose-950/40 p-4 text-sm text-rose-200">
              Could not load the IPO calendar: {cal.error}
            </p>
          ) : cal.ipos.length === 0 ? (
            <p className="rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
              No IPOs in the current window.
            </p>
          ) : (
            <div className="overflow-hidden rounded-lg border border-zinc-800">
              <table className="w-full text-sm">
                <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-4 py-2 text-left">Date</th>
                    <th className="px-4 py-2 text-left">Symbol</th>
                    <th className="px-4 py-2 text-left">Company</th>
                    <th className="px-4 py-2 text-left">Exchange</th>
                    <th className="px-4 py-2 text-right">Price</th>
                    <th className="px-4 py-2 text-left">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {cal.ipos.map((ipo, i) => (
                    <tr
                      key={`${ipo.symbol}-${ipo.date}-${i}`}
                      className="hover:bg-zinc-900/30"
                    >
                      <td className="px-4 py-2 font-mono text-zinc-400">
                        {ipo.date || "—"}
                        {ipo.date > today && (
                          <span className="ml-2 text-[10px] uppercase text-teal-400">
                            upcoming
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2 font-mono font-bold text-zinc-100">
                        {ipo.symbol || "—"}
                      </td>
                      <td className="max-w-[18rem] truncate px-4 py-2 text-zinc-300">
                        {ipo.name}
                      </td>
                      <td className="px-4 py-2 text-zinc-400">
                        {ipo.exchange || "—"}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-zinc-300">
                        {ipo.price ? `$${ipo.price}` : "—"}
                      </td>
                      <td className="px-4 py-2">
                        <StatusBadge status={ipo.status} />
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

function StatusBadge({ status }: { status: Ipo["status"] }) {
  const s = status.toLowerCase();
  const cls =
    s === "priced"
      ? "text-emerald-400"
      : s === "withdrawn"
        ? "text-rose-400"
        : s === "expected"
          ? "text-teal-400"
          : "text-zinc-500";
  return <span className={`text-xs ${cls}`}>{status || "—"}</span>;
}
