import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { StatusPill } from "@/app/components/StatusPill";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import {
  latestDailyAnalysis,
  listProposalsFiltered,
  type DailyAnalysis,
  type ProposalFilters,
  type ProposalStatus,
} from "@/lib/queries";
import { MobileProposalCard } from "./MobileProposalCard";

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

  const todaysAnalysis = await latestDailyAnalysis().catch(() => null);

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">Proposals</h1>

        <TodaysAnalysisCard analysis={todaysAnalysis} />

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
        ) : rows.length === 0 ? (
          <div className="mt-6 rounded-lg border border-zinc-800">
            <p className="p-6 text-sm text-zinc-500">No proposals yet.</p>
          </div>
        ) : (
          <>
            {/* Mobile card list */}
            <div className="mt-6 space-y-3 sm:hidden">
              {rows.map((p) => (
                <MobileProposalCard
                  key={p.id}
                  id={p.id}
                  symbol={p.symbol}
                  side={p.side}
                  quantity={String(p.quantity)}
                  limitPrice={String(p.limit_price)}
                  stopPrice={p.stop_price ? String(p.stop_price) : null}
                  rationale={p.rationale}
                  confidence={p.confidence}
                  status={p.status}
                  createdAt={String(p.created_at)}
                />
              ))}
            </div>

            {/* Desktop table */}
            <div className="mt-6 hidden overflow-hidden rounded-lg border border-zinc-800 sm:block">
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
            </div>
          </>
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

function TodaysAnalysisCard({ analysis }: { analysis: DailyAnalysis | null }) {
  if (!analysis) return null;
  const traded = analysis.proposals_passed_risk > 0;
  const firstLine =
    analysis.summary.trim().split("\n")[0]?.slice(0, 280) ||
    (traded ? "Proposed trade(s) today." : "No qualifying setups today.");
  return (
    <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-200">
          Today&apos;s analysis · {analysis.as_of}
        </h2>
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${
            traded
              ? "bg-emerald-900 text-emerald-200"
              : "bg-zinc-800 text-zinc-300"
          }`}
        >
          {traded
            ? `${analysis.proposals_passed_risk} proposal${analysis.proposals_passed_risk === 1 ? "" : "s"}`
            : "no trade"}
        </span>
      </div>
      <p className="mt-2 text-sm text-zinc-400">{firstLine}</p>
      <div className="mt-2 flex items-center gap-4 text-xs text-zinc-600">
        <span>
          {analysis.proposals_generated} considered · {analysis.proposals_blocked_risk} risk-blocked
        </span>
        <a href="/analysis" className="text-emerald-400 hover:underline">
          Full analysis →
        </a>
      </div>
    </div>
  );
}
