import { getSql } from "@/lib/db";

const ACTION_TO_STATUS = {
  approve: "approved",
  reject: "rejected",
  defer: "deferred",
} as const;

const ACTION_TO_SHADOW: Record<string, string | null> = {
  approve: "approved",
  reject: "rejected",
  defer: null,
};

export type ProposalAction = keyof typeof ACTION_TO_STATUS;

export interface ActionResult {
  ok: boolean;
  proposal?: { id: number; status: string; decided_at: string; decided_by: string };
  error?: string;
  status?: number;
}

export async function recordDecision(
  proposalId: number,
  action: ProposalAction,
  decidedBy: string,
): Promise<ActionResult> {
  const newStatus = ACTION_TO_STATUS[action];
  const sql = getSql();

  const existing = await sql<{ id: number; status: string }[]>`
    SELECT id, status FROM proposal WHERE id = ${proposalId}
  `;
  if (existing.length === 0) {
    return { ok: false, error: "Proposal not found", status: 404 };
  }
  if (existing[0].status !== "proposed") {
    return {
      ok: false,
      error: `Proposal already ${existing[0].status}`,
      status: 409,
    };
  }

  const [row] = await sql<{
    id: number;
    status: string;
    decided_at: string;
    decided_by: string;
  }[]>`
    UPDATE proposal
    SET
      status = ${newStatus},
      decided_at = NOW(),
      decided_by = ${decidedBy}
    WHERE id = ${proposalId}
    RETURNING id, status, decided_at::text AS decided_at, decided_by
  `;

  const shadowDecision = ACTION_TO_SHADOW[action];
  if (shadowDecision !== null) {
    await sql`
      UPDATE shadowposition
      SET decision = ${shadowDecision}
      WHERE proposal_id = ${proposalId} AND decision IS NULL
    `;
  }

  return { ok: true, proposal: row };
}
