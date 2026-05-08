import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getDashboardStats, listRecentProposals } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const [stats, recent] = await Promise.all([
    getDashboardStats().catch((e) => ({ error: String(e) }) as const),
    listRecentProposals(5).catch(() => []),
  ]);

  const dbError = "error" in stats ? stats.error : null;

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>

        {dbError !== null ? (
          <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
            <p className="font-medium">Database query failed</p>
            <p className="mt-1 font-mono text-xs text-rose-300/80">{dbError}</p>
            <p className="mt-2 text-rose-300/80">
              Check that <code>DATABASE_URL</code> is set in Vercel and points
              at the Neon pooled endpoint.
            </p>
          </div>
        ) : !("error" in stats) ? (
          <section className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Status"
              value={stats.halted ? "🛑 HALTED" : "✅ Running"}
              tone={stats.halted ? "warn" : "ok"}
            />
            <StatCard label="Proposals today" value={stats.proposals_today} />
            <StatCard label="Pending decisions" value={stats.proposals_pending} />
            <StatCard label="Orders today" value={stats.orders_today} />
          </section>
        ) : null}

        <section className="mt-10">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
              Recent proposals
            </h2>
            <a href="/proposals" className="text-xs text-zinc-500 hover:text-zinc-300">
              View all →
            </a>
          </div>
          <div className="mt-3 overflow-hidden rounded-lg border border-zinc-800">
            {recent.length === 0 ? (
              <p className="p-6 text-sm text-zinc-500">No proposals yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-4 py-2 text-left">Symbol</th>
                    <th className="px-4 py-2 text-left">Side</th>
                    <th className="px-4 py-2 text-right">Qty</th>
                    <th className="px-4 py-2 text-right">Limit</th>
                    <th className="px-4 py-2 text-left">Status</th>
                    <th className="px-4 py-2 text-left">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {recent.map((p) => (
                    <tr key={p.id} className="hover:bg-zinc-900/30">
                      <td className="px-4 py-2 font-mono">
                        <a href={`/proposals/${p.id}`} className="hover:text-emerald-400">
                          {p.symbol}
                        </a>
                      </td>
                      <td className="px-4 py-2">{p.side}</td>
                      <td className="px-4 py-2 text-right font-mono">{p.quantity}</td>
                      <td className="px-4 py-2 text-right font-mono">{p.limit_price}</td>
                      <td className="px-4 py-2">
                        <StatusPill status={p.status} />
                      </td>
                      <td className="px-4 py-2 text-zinc-500">
                        {new Date(p.created_at).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </main>
    </>
  );
}

function StatCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  tone?: "ok" | "warn" | "neutral";
}) {
  const toneClass =
    tone === "ok"
      ? "text-emerald-400"
      : tone === "warn"
        ? "text-amber-400"
        : "text-zinc-100";
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-4">
      <p className="text-xs uppercase tracking-wider text-zinc-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</p>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const colors: Record<string, string> = {
    proposed: "bg-zinc-700 text-zinc-100",
    approved: "bg-blue-900 text-blue-200",
    rejected: "bg-rose-900 text-rose-200",
    deferred: "bg-zinc-800 text-zinc-300",
    expired: "bg-zinc-800 text-zinc-500",
    executed: "bg-emerald-900 text-emerald-200",
    pending: "bg-zinc-700 text-zinc-100",
    submitted: "bg-blue-900 text-blue-200",
    filled: "bg-emerald-900 text-emerald-200",
    partially_filled: "bg-amber-900 text-amber-200",
    cancelled: "bg-zinc-800 text-zinc-500",
  };
  const cls = colors[status] ?? "bg-zinc-800 text-zinc-300";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}
