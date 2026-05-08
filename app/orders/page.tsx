import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { StatusPill } from "@/app/components/StatusPill";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { listRecentOrders, type Order } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function OrdersPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const orders = await listRecentOrders(200).catch(
    (e) => ({ error: String(e) }) as const,
  );
  const dbError =
    !Array.isArray(orders) && "error" in orders ? orders.error : null;
  const rows = Array.isArray(orders) ? orders : [];

  // Group by date (YYYY-MM-DD of submitted_at, fall back to filled_at).
  const groups = new Map<string, Order[]>();
  for (const o of rows) {
    const ts = o.submitted_at ?? o.filled_at;
    const key = ts ? new Date(ts).toISOString().slice(0, 10) : "unknown";
    const arr = groups.get(key) ?? [];
    arr.push(o);
    groups.set(key, arr);
  }

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Orders</h1>

        {dbError !== null ? (
          <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
            <p className="font-medium">Database query failed</p>
            <p className="mt-1 font-mono text-xs text-rose-300/80">{dbError}</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="mt-6 rounded-lg border border-zinc-800 p-6 text-sm text-zinc-500">
            No orders yet.
          </div>
        ) : (
          <div className="mt-6 space-y-8">
            {[...groups.entries()].map(([date, group]) => (
              <section key={date}>
                <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
                  {date === "unknown" ? "Unsubmitted" : date}
                </h2>
                <div className="overflow-hidden rounded-lg border border-zinc-800">
                  <table className="w-full text-sm">
                    <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                      <tr>
                        <th className="px-4 py-2 text-left">Submitted</th>
                        <th className="px-4 py-2 text-left">Symbol</th>
                        <th className="px-4 py-2 text-left">Side</th>
                        <th className="px-4 py-2 text-left">Type</th>
                        <th className="px-4 py-2 text-right">Qty</th>
                        <th className="px-4 py-2 text-right">Fill price</th>
                        <th className="px-4 py-2 text-right">Fill qty</th>
                        <th className="px-4 py-2 text-left">Status</th>
                        <th className="px-4 py-2 text-left">Broker ID</th>
                        <th className="px-4 py-2 text-left"></th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800">
                      {group.map((o) => (
                        <tr key={o.id} className="hover:bg-zinc-900/30">
                          <td className="px-4 py-2 text-zinc-500">
                            {o.submitted_at
                              ? new Date(o.submitted_at).toLocaleTimeString()
                              : "—"}
                          </td>
                          <td className="px-4 py-2 font-mono">{o.symbol}</td>
                          <td className="px-4 py-2">{o.side}</td>
                          <td className="px-4 py-2 text-zinc-400">
                            {o.order_type}
                          </td>
                          <td className="px-4 py-2 text-right font-mono">
                            {o.quantity}
                          </td>
                          <td className="px-4 py-2 text-right font-mono">
                            {o.avg_fill_price ?? "—"}
                          </td>
                          <td className="px-4 py-2 text-right font-mono">
                            {o.filled_quantity}
                          </td>
                          <td className="px-4 py-2">
                            <StatusPill status={o.status} />
                          </td>
                          <td className="px-4 py-2 font-mono text-xs text-zinc-500">
                            {o.broker_order_id ?? "—"}
                          </td>
                          <td className="px-4 py-2">
                            {o.proposal_id !== null ? (
                              <a
                                href={`/proposals/${o.proposal_id}`}
                                className="text-xs text-emerald-400 hover:underline"
                              >
                                Proposal #{o.proposal_id}
                              </a>
                            ) : (
                              <span className="text-xs text-zinc-600">—</span>
                            )}
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
      </main>
    </>
  );
}
