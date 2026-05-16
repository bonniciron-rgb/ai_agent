/**
 * POST /api/sync
 *
 * Triggers the `daily-trade-loop` GitHub Actions workflow (workflow_dispatch),
 * which ingests fresh bars, reads the live T212 portfolio, and runs the agent.
 * Body: { dryRun?: boolean } — defaults to true (no DB writes / no Telegram).
 *
 * Requires GITHUB_DISPATCH_TOKEN (a GitHub token with `actions:write` scope)
 * in the dashboard's environment.
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REPO = "bonniciron-rgb/ai_agent";
const WORKFLOW = "daily.yml";

export interface SyncResult {
  ok: boolean;
  configured: boolean;
  dryRun?: boolean;
  status?: number;
  message: string;
  actionsUrl?: string;
}

export async function POST(request: Request) {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const token = process.env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    const result: SyncResult = {
      ok: false,
      configured: false,
      message:
        "GITHUB_DISPATCH_TOKEN is not set. Add a GitHub fine-grained token with Actions: read-and-write scope in Vercel → Settings → Environment Variables, then redeploy.",
    };
    return NextResponse.json(result);
  }

  // Default to a dry run unless the caller explicitly opts into a full run.
  let dryRun = true;
  try {
    const body = (await request.json()) as { dryRun?: boolean };
    if (body?.dryRun === false) dryRun = false;
  } catch {
    // No JSON body — keep the safe default.
  }

  const actionsUrl = `https://github.com/${REPO}/actions/workflows/${WORKFLOW}`;
  try {
    const res = await fetch(
      `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
        },
        body: JSON.stringify({
          ref: "main",
          inputs: { dry_run: String(dryRun) },
        }),
      },
    );
    if (res.status === 204) {
      const result: SyncResult = {
        ok: true,
        configured: true,
        dryRun,
        message: `Sync triggered (${dryRun ? "dry run — no writes" : "full run"}). Follow progress in GitHub Actions.`,
        actionsUrl,
      };
      return NextResponse.json(result);
    }
    const body = await res.text();
    const result: SyncResult = {
      ok: false,
      configured: true,
      status: res.status,
      message: `GitHub returned ${res.status}: ${body.slice(0, 200)}`,
      actionsUrl,
    };
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const result: SyncResult = {
      ok: false,
      configured: true,
      message: `Request to GitHub failed: ${message}`,
      actionsUrl,
    };
    return NextResponse.json(result);
  }
}
