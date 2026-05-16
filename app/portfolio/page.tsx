/**
 * Portfolio page — live Trading 212 holdings (cash + open positions).
 *
 * Server component: auth gate only. The live T212 fetch happens client-side
 * via /api/portfolio so the page renders instantly and refreshes on demand.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { PortfolioClient } from "./PortfolioClient";

export const dynamic = "force-dynamic";

export default async function PortfolioPage() {
  const token = cookies().get(SESSION_COOKIE)?.value;
  const session = token ? await verifySession(token) : null;
  if (!session) redirect("/login");

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <Nav session={session} />
      <div className="mx-auto max-w-5xl px-6 py-8 space-y-4">
        <div>
          <h1 className="text-2xl font-semibold">Portfolio</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Live Trading 212 holdings. Symbols you hold can be added to the
            watchlist so the agent screens them each day.
          </p>
        </div>
        <PortfolioClient />
      </div>
    </div>
  );
}
