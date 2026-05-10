"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface Props {
  proposalId: number;
  symbol: string;
  side: string;
  quantity: string;
  limitPrice: string;
  currentStatus: string;
  decidedAt?: string | null;
  decidedBy?: string | null;
}

type Action = "approve" | "defer" | "reject";

const ACTION_LABEL: Record<Action, string> = {
  approve: "Approve",
  defer: "Defer",
  reject: "Reject",
};

const ACTION_BTN: Record<Action, string> = {
  approve: "bg-emerald-600 hover:bg-emerald-500 text-white",
  defer: "bg-zinc-700 hover:bg-zinc-600 text-zinc-100",
  reject: "bg-rose-600 hover:bg-rose-500 text-white",
};

const ACTION_CONFIRM_BTN: Record<Action, string> = {
  approve: "bg-emerald-600 hover:bg-emerald-500 text-white",
  defer: "bg-zinc-700 hover:bg-zinc-600 text-zinc-100",
  reject: "bg-rose-600 hover:bg-rose-500 text-white",
};

const DECISION_BADGE: Record<string, string> = {
  approved: "text-emerald-400",
  rejected: "text-rose-400",
  deferred: "text-zinc-400",
};

export function ApprovalActions(props: Props) {
  const [pending, setPending] = useState<Action | null>(null);
  const [confirming, setConfirming] = useState<Action | null>(null);
  const [toast, setToast] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const router = useRouter();

  function showToast(kind: "success" | "error", text: string) {
    setToast({ kind, text });
    setTimeout(() => setToast(null), 2500);
  }

  async function handleConfirm(action: Action) {
    setPending(action);
    setConfirming(null);
    try {
      const res = await fetch(`/api/proposals/${props.proposalId}/${action}`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        showToast("error", body.error ?? `Failed: ${res.status}`);
        return;
      }
      navigator.vibrate?.(50);
      showToast("success", `${ACTION_LABEL[action]}d successfully`);
      router.refresh();
    } catch {
      showToast("error", "Network error — please try again");
    } finally {
      setPending(null);
    }
  }

  if (props.currentStatus !== "proposed") {
    const badgeCls = DECISION_BADGE[props.currentStatus] ?? "text-zinc-400";
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
        <p className="text-xs uppercase tracking-wider text-zinc-500">Decision</p>
        <p className={`mt-1 font-semibold uppercase ${badgeCls}`}>
          {props.currentStatus}
        </p>
        {props.decidedBy && (
          <p className="mt-1 text-xs text-zinc-500">by {props.decidedBy}</p>
        )}
        {props.decidedAt && (
          <p className="mt-0.5 text-xs text-zinc-600">
            {new Date(props.decidedAt).toLocaleString()}
          </p>
        )}
      </div>
    );
  }

  return (
    <>
      {/* Mobile sticky bottom bar */}
      <div className="sm:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-zinc-800 bg-zinc-950/90 backdrop-blur px-4 py-3">
        <div className="flex gap-2">
          {(["approve", "defer", "reject"] as Action[]).map((action) => (
            <button
              key={action}
              onClick={() => setConfirming(action)}
              disabled={pending !== null}
              className={`flex-1 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 ${ACTION_BTN[action]}`}
            >
              {pending === action ? "..." : ACTION_LABEL[action]}
            </button>
          ))}
        </div>
      </div>

      {/* Desktop inline buttons */}
      <div className="hidden sm:block rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
        <p className="text-xs uppercase tracking-wider text-zinc-500 mb-3">Action</p>
        <div className="flex gap-2">
          {(["approve", "defer", "reject"] as Action[]).map((action) => (
            <button
              key={action}
              onClick={() => setConfirming(action)}
              disabled={pending !== null}
              className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors disabled:opacity-50 ${ACTION_BTN[action]}`}
            >
              {pending === action ? "..." : ACTION_LABEL[action]}
            </button>
          ))}
        </div>
      </div>

      {/* Spacer for mobile sticky bar */}
      <div className="sm:hidden h-20" />

      {/* Confirmation overlay */}
      {confirming && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60"
          onClick={() => setConfirming(null)}
        >
          <div
            className="w-full max-w-sm rounded-t-2xl sm:rounded-2xl border border-zinc-700 bg-zinc-900 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-base font-semibold">
              {ACTION_LABEL[confirming]} proposal?
            </h2>
            <p className="mt-2 text-sm text-zinc-400">
              <span className="font-mono font-medium text-zinc-100">{props.symbol}</span>
              {" "}
              {props.side.toUpperCase()} {props.quantity} @ ${props.limitPrice}
            </p>
            <div className="mt-5 flex gap-3">
              <button
                onClick={() => setConfirming(null)}
                className="flex-1 rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-700"
              >
                Cancel
              </button>
              <button
                onClick={() => handleConfirm(confirming)}
                className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${ACTION_CONFIRM_BTN[confirming]}`}
              >
                Confirm {ACTION_LABEL[confirming]}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-20 sm:bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg px-4 py-2.5 text-sm font-medium shadow-lg ${
            toast.kind === "success"
              ? "bg-emerald-900 text-emerald-100 border border-emerald-700"
              : "bg-rose-900 text-rose-100 border border-rose-700"
          }`}
        >
          {toast.text}
        </div>
      )}
    </>
  );
}
