/**
 * Typed env-var access. Throws at call time if a required var is missing,
 * so a misconfigured Vercel project surfaces as a clear 500 instead of a
 * silent undefined.
 */

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

export const env = {
  /** Telegram bot token — used for both webhook auth and Login Widget HMAC. */
  TELEGRAM_BOT_TOKEN: () => required("TELEGRAM_BOT_TOKEN"),

  /** Numeric chat id of the only authorized user (single-user MVP). */
  TELEGRAM_CHAT_ID: () => required("TELEGRAM_CHAT_ID"),

  /** Secret used to sign session cookies. Defaults to the bot token if unset. */
  SESSION_SECRET: () =>
    process.env.SESSION_SECRET || required("TELEGRAM_BOT_TOKEN"),
};

/**
 * Public bot username for the Telegram Login Widget.  Inlined at build time
 * via the NEXT_PUBLIC_ prefix so it can be used in client components.
 */
export const PUBLIC_BOT_USERNAME = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME;
