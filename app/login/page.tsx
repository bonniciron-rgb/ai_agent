import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import Script from "next/script";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { PUBLIC_BOT_USERNAME } from "@/lib/env";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (session) redirect("/");

  const botLink = PUBLIC_BOT_USERNAME ? `https://t.me/${PUBLIC_BOT_USERNAME}` : null;

  return (
    <main className="mx-auto max-w-md px-6 py-24">
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-3 text-zinc-400">
        Authenticate with the Telegram account that owns the trading bot.
      </p>

      {/* Primary path: bot magic link */}
      <div className="mt-8 rounded-lg border border-zinc-800 bg-zinc-900/50 p-6">
        <h2 className="text-sm font-medium uppercase tracking-wider text-zinc-500">
          Recommended — sign in via bot DM
        </h2>
        <ol className="mt-4 space-y-2 text-sm text-zinc-300 list-decimal list-inside">
          <li>
            Open a chat with{" "}
            {botLink ? (
              <a
                href={botLink}
                className="text-emerald-400 hover:underline"
                target="_blank"
                rel="noreferrer"
              >
                @{PUBLIC_BOT_USERNAME}
              </a>
            ) : (
              <span className="text-amber-400">your bot</span>
            )}
          </li>
          <li>
            Send <code className="rounded bg-zinc-800 px-1.5 py-0.5">/login</code>
          </li>
          <li>Tap the link the bot replies with — you&apos;ll be signed in instantly</li>
        </ol>
        <p className="mt-4 text-xs text-zinc-500">Link expires 5 minutes after the bot generates it.</p>
      </div>

      {/* Fallback: Telegram Login Widget */}
      <details className="mt-6 group">
        <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-300">
          Or use the Telegram Login Widget (legacy)
        </summary>
        <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900/30 p-6">
          {PUBLIC_BOT_USERNAME ? (
            <>
              <div
                id="telegram-login-container"
                data-telegram-login={PUBLIC_BOT_USERNAME}
                data-size="large"
                data-auth-url="/api/auth/telegram"
                data-request-access="write"
              />
              <Script
                src="https://telegram.org/js/telegram-widget.js?22"
                strategy="afterInteractive"
                data-telegram-login={PUBLIC_BOT_USERNAME}
                data-size="large"
                data-auth-url="/api/auth/telegram"
                data-request-access="write"
              />
            </>
          ) : (
            <p className="text-sm text-amber-400">
              <code>NEXT_PUBLIC_TELEGRAM_BOT_USERNAME</code> not set.
            </p>
          )}
        </div>
      </details>

      <p className="mt-8 text-xs text-zinc-500">
        Only the chat ID configured as <code>TELEGRAM_CHAT_ID</code> can sign in.
      </p>
    </main>
  );
}
