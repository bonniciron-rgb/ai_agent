import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { StatusPill } from "@/app/components/StatusPill";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import {
  listProposalsFiltered,
  type ProposalFilters,
  type ProposalStatus,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

const VALID_STATUSES: ReadonlySet<ProposalStatus> = new Set([
  "proposed",
  "approved",
  "rejected",
  "deferred",
  "expired",
  "executed",
]);

export default async function ProposalsPage({
  searchParams,
}: {
  searchParams?: { status?: string; symbol?: string; from?: string };
}) {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const filters: ProposalFilters = {};
  if (
    searchParams?.status &&
    VALID_STATUSES.has(searchParams.status as ProposalStatus)
  ) {
    filters.status = searchParams.status as ProposalStatus;
  }
  if (searchParams?.symbol) filters.symbol = searchParams.symbol;
  if (searchParams?.from && /^\d{4}-\d{2}-\d{2}$/.test(searchParams.from)) {
    filters.from = searchParams.from;
  }

  const proposals = await listProposalsFiltered(filters, 100).catch(
    (e) => ({ error: String(e) }) as const,
  );
  const dbError =
    !Array.isArray(proposals) && "error" in proposals ? proposals.error : null;
  const rows = Array.isArray(proposals) ? proposals : [];

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Proposals</h1>

        <form
          method="get"
          className="mt-6 flex flex-wrap items-end gap-3 text-sm"
        >
          <Field label="Status">
            <select
              name="status"
              defaultValue={filters.status ?? ""}
              className="rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-zinc-100"
            >
              <option value="">All</option>
              {Array.from(VALID_STATUSES).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Symbol">
            <input
              type="text"
              name="symbol"
              defaultValue={filters.symbol ?? ""}
              placeholder="e.g. AAPL"
              className="w-28 rounded border border-zinc-800 bg-zinc-900 px-2 py-1 font-mono text-zinc-100"
            />
          </Field>
          <Field label="From">
            <input
              type="date"
              name="from"
              defaultValue={filters.from ?? ""}
              className="rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-zinc-100"
            />
          </Field>
          <button
            type="submit"
            className="rounded border border-zinc-700 bg-zinc-800 px-3 py-1 text-zinc-100 hover:bg-zinc-700"
          >
            Apply
          </button>
          <a
            href="/proposals"
            className="text-xs text-zinc-500 hover:text-zinc-300"
          >
            Reset
          </a>
        </form>

        {dbError !== null ? (
          <div className="mt-6 rounded-lg border border-rose-900 bg-rose-950/50 p-4 text-sm text-rose-200">
            <p className="font-medium">Database query failed</p>
            <p className="mt-1 font-mono text-xs text-rose-300/80">{dbError}</p>
          </div>
        ) : (
          <div className="mt-6 overflow-hidden rounded-lg border border-zinc-800">
            {rows.length === 0 ? (
              <p className="p-6 text-sm text-zinc-500">No proposals yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-zinc-900/50 text-xs uppercase tracking-wider text-zinc-500">
                  <tr>
                    <th className="px-4 py-2 text-left">Created</th>
                    <th className="px-4 py-2 text-left">Symbol</th>
                    <th className="px-4 py-2 text-left">Side</th>
                    <th className="px-4 py-2 text-right">Qty</th>
                    <th className="px-4 py-2 text-right">Limit</th>
                    <th className="px-4 py-2 text-right">Stop</th>
                    <th className="px-4 py-2 text-left">Status</th>
                    <th className="px-4 py-2 text-left">Decided by</th>
                    <th className="px-4 py-2 text-left"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {rows.map((p) => (
                    <tr key={p.id} className="hover:bg-zinc-900/30">
                      <td className="px-4 py-2 text-zinc-500">
                        {new Date(p.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2 font-mono">{p.symbol}</td>
                      <td className="px-4 py-2">{p.side}</td>
                      <td className="px-4 py-2 text-right font-mono">
                        {p.quantity}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        {p.limit_price}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-zinc-500">
                        {p.stop_price ?? "—"}
                      </td>
                      <td className="px-4 py-2">
                        <StatusPill status={p.status} />
                      </td>
                      <td className="px-4 py-2 text-zinc-500">
                        {p.decided_by ?? "—"}
                      </td>
                      <td className="px-4 py-2">
                        <a
                          href={`/proposals/${p.id}`}
                          className="text-xs text-emerald-400 hover:underline"
                        >
                          View →
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </main>
    </>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wider text-zinc-500">
        {label}
      </span>
      {children}
    </label>
  );
}
