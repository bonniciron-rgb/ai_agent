/**
 * Watchlist editor — DB-backed, bootstrapped from config/watchlist.yaml on first load.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { bootstrapWatchlistFromYaml } from "@/lib/watchlist-bootstrap";
import { WatchlistClient } from "./WatchlistClient";

export const dynamic = "force-dynamic";

export default async function WatchlistPage() {
  const token = cookies().get(SESSION_COOKIE)?.value;
  const session = token ? await verifySession(token) : null;
  if (!session) redirect("/login");

  try {
    await bootstrapWatchlistFromYaml();
  } catch {
    // best-effort — UI will show whatever is in DB (possibly empty)
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <Nav session={session} />
      <div className="mx-auto max-w-5xl px-6 py-8 space-y-4">
        <div>
          <h1 className="text-2xl font-semibold">Watchlist</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Tickers the agent screens each trading day.
          </p>
        </div>
        <WatchlistClient />
      </div>
    </div>
  );
}
