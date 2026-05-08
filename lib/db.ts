/**
 * Single Postgres client for the dashboard.
 *
 * `postgres.js` opens a connection pool and reuses it across requests
 * within the same Vercel function instance.  We use Neon's pooled
 * endpoint (the URL with -pooler in the host) so that pgBouncer handles
 * connection multiplexing across cold starts.
 */

import postgres from "postgres";

const connectionString = process.env.DATABASE_URL;

if (!connectionString) {
  throw new Error("DATABASE_URL is not set");
}

// `prepare: false` is required for pgBouncer transaction-pooling mode (Neon's pooled endpoint).
export const sql = postgres(connectionString, {
  prepare: false,
  ssl: "require",
  max: 5,
  idle_timeout: 20,
});
