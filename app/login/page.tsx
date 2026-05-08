import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import Script from "next/script";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import { PUBLIC_BOT_USERNAME } from "@/lib/env";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const session = await verifySession(cookies().get(SESSION_COOKIE)?.value);
  if (session) redirect("/");

  return (
    <main className="mx-auto max-w-md px-6 py-24">
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-3 text-zinc-400">
        Authenticate with the Telegram account that owns the trading bot.
      </p>

      <div className="mt-8 rounded-lg border border-zinc-800 bg-zinc-900/50 p-6">
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
            <code>NEXT_PUBLIC_TELEGRAM_BOT_USERNAME</code> is not set. Configure
            it in Vercel env vars to enable the login widget.
          </p>
        )}
      </div>

      <p className="mt-6 text-xs text-zinc-500">
        Only the chat ID configured as <code>TELEGRAM_CHAT_ID</code> can sign in.
      </p>
    </main>
  );
}
