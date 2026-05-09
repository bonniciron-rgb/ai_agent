import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Nav } from "@/app/components/Nav";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { listSignalChannels } from "@/lib/queries";
import { SignalsClient } from "./SignalsClient";

export const dynamic = "force-dynamic";

export default async function SignalsPage() {
  const token = cookies().get(SESSION_COOKIE)?.value;
  const session = token ? await verifySession(token) : null;
  if (!session) redirect("/login");

  let channels = [];
  let fetchError: string | null = null;
  try {
    channels = await listSignalChannels();
  } catch (e: unknown) {
    fetchError = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <Nav session={session} />
      <div className="mx-auto max-w-5xl px-6 py-8 space-y-4">
        <div>
          <h1 className="text-2xl font-semibold">Signal Sources</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Telegram channels Claude reads before generating trade proposals.
          </p>
        </div>

        {fetchError && (
          <div className="rounded-md bg-rose-950 border border-rose-800 px-4 py-3 text-sm text-rose-300">
            Could not load channels: {fetchError}
          </div>
        )}

        <SignalsClient initial={channels} />
      </div>
    </div>
  );
}
