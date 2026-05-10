"use client";

import { StatusPill } from "@/app/components/StatusPill";

interface Props {
  id: number;
  symbol: string;
  side: string;
  quantity: string;
  limitPrice: string;
  stopPrice: string | null;
  rationale: string;
  confidence: string;
  status: string;
  createdAt: string;
}

export function MobileProposalCard(props: Props) {
  const truncatedRationale =
    props.rationale.length > 120
      ? props.rationale.slice(0, 120) + "..."
      : props.rationale;

  return (
    <a
      href={`/proposals/${props.id}`}
      className="block rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 hover:border-zinc-700 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-lg font-bold text-zinc-100">
            {props.symbol}
          </span>
          <span className="text-sm text-zinc-400">
            {props.side.toUpperCase()} {props.quantity}
          </span>
        </div>
        <StatusPill status={props.status} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
        <span className="rounded bg-zinc-800 px-1.5 py-0.5 font-medium text-zinc-300">
          {props.confidence}
        </span>
        <span>
          Limit{" "}
          <span className="font-mono text-zinc-300">${props.limitPrice}</span>
        </span>
        {props.stopPrice && (
          <span>
            Stop{" "}
            <span className="font-mono text-zinc-300">${props.stopPrice}</span>
          </span>
        )}
      </div>

      {truncatedRationale && (
        <p className="mt-2 text-xs leading-5 text-zinc-500">
          {truncatedRationale}
        </p>
      )}

      <div className="mt-3 flex items-center justify-between text-xs text-zinc-600">
        <span>{new Date(props.createdAt).toLocaleString()}</span>
        <span className="text-emerald-500">View →</span>
      </div>
    </a>
  );
}
