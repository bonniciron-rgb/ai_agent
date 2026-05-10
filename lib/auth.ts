/**
 * Auth helpers — Telegram Login Widget HMAC verification + session JWTs.
 *
 * Verification flow (https://core.telegram.org/widgets/login#checking-authorization):
 * 1. Telegram sends id, first_name, username, auth_date, hash, ...
 * 2. We rebuild `data_check_string` from sorted key=value lines (excluding hash).
 * 3. secret_key = SHA-256(bot_token) raw bytes.
 * 4. computed_hash = HMAC-SHA256(data_check_string, secret_key) hex.
 * 5. Reject if computed_hash != received hash, or auth_date too old.
 * 6. Reject if id != TELEGRAM_CHAT_ID (single-user MVP).
 */

import { SignJWT, jwtVerify } from "jose";
import { env } from "./env";

export const SESSION_COOKIE = "ai_agent_session";
const SESSION_TTL_SECONDS = env.SESSION_TTL_DAYS() * 24 * 60 * 60;
const TELEGRAM_AUTH_MAX_AGE_SECONDS = 60 * 60 * 24; // 1 day

export interface TelegramAuthData {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
}

export interface SessionPayload {
  uid: string;
  username?: string;
}

/** Verify the HMAC on Telegram Login Widget data. */
export async function verifyTelegramAuth(
  data: TelegramAuthData,
  botToken: string,
): Promise<boolean> {
  const { hash, ...rest } = data;

  // 1. Build the data-check string (sorted key=value lines).
  const dataCheckString = Object.entries(rest)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${k}=${v}`)
    .sort()
    .join("\n");

  // 2. secret_key = SHA-256(bot_token).
  const enc = new TextEncoder();
  const secretKey = await crypto.subtle.digest("SHA-256", enc.encode(botToken));

  // 3. HMAC-SHA256(data_check_string, secret_key).
  const key = await crypto.subtle.importKey(
    "raw",
    secretKey,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(dataCheckString));

  // 4. Hex-encode and compare.
  const hex = Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  return hex === hash;
}

/** Reject auth replays older than 1 day. */
export function isAuthRecent(authDate: number): boolean {
  const now = Math.floor(Date.now() / 1000);
  return now - authDate < TELEGRAM_AUTH_MAX_AGE_SECONDS;
}

/** Issue a signed session JWT for the given user. */
export async function createSession(payload: SessionPayload): Promise<string> {
  const secret = new TextEncoder().encode(env.SESSION_SECRET());
  return new SignJWT({ uid: payload.uid, username: payload.username })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${SESSION_TTL_SECONDS}s`)
    .sign(secret);
}

/** Verify a session JWT and return the payload, or null if invalid/expired. */
export async function verifySession(
  token: string | undefined,
): Promise<SessionPayload | null> {
  if (!token) return null;
  try {
    const secret = new TextEncoder().encode(env.SESSION_SECRET());
    const { payload } = await jwtVerify(token, secret);
    if (typeof payload.uid !== "string") return null;
    return {
      uid: payload.uid,
      username:
        typeof payload.username === "string" ? payload.username : undefined,
    };
  } catch {
    return null;
  }
}

export const SESSION_TTL_MS = SESSION_TTL_SECONDS * 1000;
