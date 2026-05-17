import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { getLatest13F, MANAGERS, type Report } from "@/lib/thirteenf";

export const dynamic = "force-dynamic";

export default async function LeadersPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  const reports = await Promise.all(MANAGERS.map((m) => getLatest13F(m)));

  return (
    <>
      <Nav session={session} />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="text-2xl font-semibold tracking-tight">
          Market Leaders
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          Latest disclosed equity holdings of widely-followed institutional
          investors, from their quarterly SEC 13F filings. Filed up to 45 days
          after quarter-end, so positions reflect a recent — not live —
          snapshot.
        </p>

        <div className="mt-6 space-y-6">
          {reports.map((r) => (
            <ManagerCard key={r.cik} report={r} />
          ))}
        </div>
      </main>
    </>
  );
}

function ManagerCard({ report }: { report: Report }) {
  return (
    <section className="overflow-hidden rounded-lg border border-zinc-800">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-zinc-800 bg-zinc-900/50 px-4 py-3">
        <h2 className="font-medium text-zinc-100">{report.manager}</h2>
        <span className="text-xs text-zinc-500">
          {report.periodOfReport
            ? `As of ${report.periodOfReport}`
            : "No 13F data"}
          {report.holdings.length > 0
            ? ` · ${report.holdings.length} holdings · ${money(report.totalValue)}`
            : ""}
        </span>
      </div>

      {report.error ? (
        <p className="px-4 py-6 text-sm text-zinc-500">
          Could not load 13F filing: {report.error}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-zinc-900/30 text-xs uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-4 py-2 text-left">#</th>
              <th className="px-4 py-2 text-left">Holding</th>
              <th className="px-4 py-2 text-right">Value</th>
              <th className="px-4 py-2 text-right">Portfolio %</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {report.holdings.slice(0, 10).map((h, i) => (
              <tr key={h.cusip || h.issuer} className="hover:bg-zinc-900/30">
                <td className="px-4 py-2 text-zinc-600">{i + 1}</td>
                <td className="px-4 py-2 text-zinc-100">{h.issuer}</td>
                <td className="px-4 py-2 text-right font-mono text-zinc-300">
                  {money(h.value)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-zinc-300">
                  {(h.pct * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** Compact USD formatting: $75.3B, $1.2B, $340M, $12K. */
function money(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}
