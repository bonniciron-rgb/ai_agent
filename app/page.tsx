export default function HomePage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">AI Trading Agent</h1>
      <p className="mt-3 text-zinc-400">
        Dashboard scaffold. Sign-in and live data land in M13 / M14.
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
          <dt className="text-zinc-400">Frontend</dt>
          <dd className="text-zinc-300">Next.js 14 (App Router)</dd>
          <dt className="text-zinc-400">Auth</dt>
          <dd className="text-zinc-300">Telegram Login (pending — M13)</dd>
        </dl>
      </section>
    </main>
  );
}
