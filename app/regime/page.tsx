import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { RegimeClient } from "./RegimeClient";

export const dynamic = "force-dynamic";

export default async function RegimePage() {
  const token = cookies().get(SESSION_COOKIE)?.value;
  const session = token ? await verifySession(token) : null;
  if (!session) redirect("/login");

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <Nav session={session} />
      <div className="mx-auto max-w-5xl px-6 py-8 space-y-4">
        <div>
          <h1 className="text-2xl font-semibold">Market Regime</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Daily macro regime classification from SPY and VIX signals.
          </p>
        </div>
        <RegimeClient />
      </div>
    </div>
  );
}
