/**
 * StatusPill — coloured badge for ProposalStatus or OrderStatus values.
 *
 * Used on the dashboard, proposals list/detail, and orders pages.
 */

const COLORS: Record<string, string> = {
  // ProposalStatus
  proposed: "bg-zinc-700 text-zinc-100",
  approved: "bg-blue-900 text-blue-200",
  rejected: "bg-rose-900 text-rose-200",
  deferred: "bg-zinc-800 text-zinc-300",
  expired: "bg-zinc-800 text-zinc-500",
  executed: "bg-emerald-900 text-emerald-200",
  // OrderStatus
  pending: "bg-zinc-700 text-zinc-100",
  submitted: "bg-blue-900 text-blue-200",
  filled: "bg-emerald-900 text-emerald-200",
  partially_filled: "bg-amber-900 text-amber-200",
  cancelled: "bg-zinc-800 text-zinc-500",
};

export function StatusPill({ status }: { status: string }) {
  const cls = COLORS[status] ?? "bg-zinc-800 text-zinc-300";
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {status}
    </span>
  );
}
