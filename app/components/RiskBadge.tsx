/**
 * Per-proposal risk score badge — 1 (lowest risk) to 5 (highest).
 * Green for low (1-2), amber for moderate (3), rose for high (4-5).
 * The score's reason, when present, shows on hover.
 */
export function RiskBadge({
  score,
  reason,
}: {
  score: number | null;
  reason?: string | null;
}) {
  if (score == null) {
    return <span className="text-zinc-600">—</span>;
  }
  const tone =
    score <= 2
      ? "bg-emerald-900/60 text-emerald-200"
      : score === 3
        ? "bg-amber-900/60 text-amber-200"
        : "bg-rose-900/60 text-rose-200";
  return (
    <span
      title={reason ?? undefined}
      className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}
    >
      {score}/5
    </span>
  );
}
