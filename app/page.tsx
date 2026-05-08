import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (!session) redirect("/login");

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <header className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">
          AI Trading Agent
        </h1>
        <div className="text-sm text-zinc-400">
          {session.username ? `@${session.username}` : `user ${session.uid}`}
          <a
            href="/api/auth/logout"
            className="ml-4 text-zinc-500 hover:text-zinc-300"
          >
            Sign out
          </a>
        </div>
      </header>

      <p className="mt-3 text-zinc-400">
        Dashboard scaffold. Live data lands in M14.
      </p>

      <section className="mt-10 rounded-lg border border-zinc-800 bg-zinc-900/50 p-6">
        <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
          Status
        </h2>
        <dl className="mt-4 grid grid-cols-2 gap-y-3 text-sm">
          <dt className="text-zinc-400">Webhook</dt>
          <dd>
            <a
              href="/api/telegram_webhook"
              className="text-emerald-400 hover:underline"
            >
              /api/telegram_webhook
            </a>
          </dd>
          <dt className="text-zinc-400">Auth</dt>
          <dd className="text-emerald-400">Telegram session active</dd>
          <dt className="text-zinc-400">Proposals</dt>
          <dd className="text-zinc-500">— (M14)</dd>
          <dt className="text-zinc-400">Orders</dt>
          <dd className="text-zinc-500">— (M14)</dd>
        </dl>
      </section>
    </main>
  );
}
