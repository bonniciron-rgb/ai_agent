import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import {
  getShadowWindowStats,
  listClosedShadowPositions,
  type ShadowPosition,
  type ShadowWindowStats,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function ShadowPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const [stats7d, stats30d, stats90d, positions] = await Promise.all([
    getShadowWindowStats(7).catch(() => null as ShadowWindowStats | null),
    getShadowWindowStats(30).catch(() => null as ShadowWindowStats | null),
    getShadowWindowStats(90).catch(() => null as ShadowWindowStats | null),
    listClosedShadowPositions(200).catch(() => [] as ShadowPosition[]),
  ]);

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Shadow P&L</h1>
        <p className="mt-2 text-sm text-zinc-400">
          Hypothetical performance of every proposal — approved and rejected —
          to compare agent alpha vs. gut instinct.
        </p>

        {/* Window summary cards */}
        <div className="mt-8 grid gap-4 sm:grid-cols-3">
          {[
            { label: "7-day", stats: stats7d },
            { label: "30-day", stats: stats30d },
            { label: "90-day", stats: stats90d },
          ].map(({ label, stats }) => (
            <WindowCard key={label} label={label} stats={stats} />
          ))}
        </div>

        {/* Closed positions table */}
        <h2 className="mt-10 text-lg font-medium">Closed shadow positions</h2>
        <div className="mt-4 overflow-hidden rounded-lg border border-zinc-800">
          {positions.length === 0 ? (
            <p className="p-6 text-sm text-zinc-500">
              No closed shadow positions yet. They appear here once the MTM job
              closes them (after TP/SL hit or 5 trading days).
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="px-4 py-2 text-left">Symbol</th>
                  <th className="px-4 py-2 text-left">Side</th>
                  <th className="px-4 py-2 text-left">Decision</th>
                  <th className="px-4 py-2 text-left">Opened</th>
                  <th className="px-4 py-2 text-right">Open price</th>
                  <th className="px-4 py-2 text-left">Closed</th>
                  <th className="px-4 py-2 text-right">Close price</th>
                  <th className="px-4 py-2 text-right">P&L</th>
                  <th className="px-4 py-2 text-right">%</th>
                  <th className="px-4 py-2 text-left"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {positions.map((pos) => {
                  const pnl = pos.pnl ?? 0;
                  const pct =
                    pos.opened_price > 0
                      ? ((pnl / pos.opened_price) * 100).toFixed(2)
                      : "—";
                  const isPositive = pnl >= 0;
                  return (
                    <tr key={pos.id} className="hover:bg-zinc-900/30">
                      <td className="px-4 py-2 font-mono">{pos.symbol}</td>
                      <td className="px-4 py-2 capitalize">{pos.side}</td>
                      <td className="px-4 py-2">
                        <DecisionPill decision={pos.decision} />
                      </td>
                      <td className="px-4 py-2 text-zinc-400">
                        {new Date(pos.opened_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        {fmtPrice(pos.opened_price)}
                      </td>
                      <td className="px-4 py-2 text-zinc-400">
                        {pos.closed_at
                          ? new Date(pos.closed_at).toLocaleDateString()
                          : "—"}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        {pos.closed_price != null
                          ? fmtPrice(pos.closed_price)
                          : "—"}
                      </td>
                      <td
                        className={`px-4 py-2 text-right font-mono ${isPositive ? "text-emerald-400" : "text-rose-400"}`}
                      >
                        {pnl >= 0 ? "+" : ""}
                        {pnl.toFixed(2)}
                      </td>
                      <td
                        className={`px-4 py-2 text-right text-xs ${isPositive ? "text-emerald-400" : "text-rose-400"}`}
                      >
                        {pct !== "—" ? `${pnl >= 0 ? "+" : ""}${pct}%` : "—"}
                      </td>
                      <td className="px-4 py-2">
                        <a
                          href={`/proposals/${pos.proposal_id}`}
                          className="text-xs text-emerald-400 hover:underline"
                        >
                          View →
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </main>
    </>
  );
}

function WindowCard({
  label,
  stats,
}: {
  label: string;
  stats: ShadowWindowStats | null;
}) {
  if (!stats) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
        <p className="text-sm font-medium text-zinc-400">{label}</p>
        <p className="mt-2 text-xs text-zinc-600">No data available</p>
      </div>
    );
  }

  const fmtPnl = (pnl: number) => {
    const abs = Math.abs(pnl).toFixed(2);
    return pnl >= 0 ? `+£${abs}` : `-£${abs}`;
  };

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
      <p className="text-sm font-medium uppercase tracking-wider text-zinc-400">
        {label}
      </p>
      <dl className="mt-3 space-y-2 text-sm">
        <div className="flex justify-between">
          <dt className="text-zinc-500">Approved P&L</dt>
          <dd
            className={`font-mono font-medium ${stats.approved_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}
          >
            {fmtPnl(stats.approved_pnl)}{" "}
            <span className="text-xs text-zinc-500">
              ({stats.approved_count})
            </span>
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-zinc-500">Rejected P&L</dt>
          <dd
            className={`font-mono font-medium ${stats.rejected_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}
          >
            {fmtPnl(stats.rejected_pnl)}{" "}
            <span className="text-xs text-zinc-500">
              ({stats.rejected_count})
            </span>
          </dd>
        </div>
      </dl>
    </div>
  );
}

function DecisionPill({ decision }: { decision: string | null }) {
  const colours: Record<string, string> = {
    approved:
      "bg-emerald-950 text-emerald-300 border border-emerald-800",
    rejected: "bg-rose-950 text-rose-300 border border-rose-800",
    edited: "bg-amber-950 text-amber-300 border border-amber-800",
    expired: "bg-zinc-800 text-zinc-400 border border-zinc-700",
  };
  const cls =
    colours[decision ?? ""] ?? "bg-zinc-800 text-zinc-400 border border-zinc-700";
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}
    >
      {decision ?? "pending"}
    </span>
  );
}

function fmtPrice(price: number): string {
  return `$${price.toFixed(2)}`;
}
