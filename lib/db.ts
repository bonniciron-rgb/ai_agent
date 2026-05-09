/**
 * Single Postgres client for the dashboard.
 *
 * `postgres.js` opens a connection pool and reuses it across requests
 * within the same Vercel function instance.  We use Neon's pooled
 * endpoint (the URL with -pooler in the host) so that pgBouncer handles
 * connection multiplexing across cold starts.
 *
 * The client is constructed lazily so that `next build` does not crash
 * at module-evaluation time when `DATABASE_URL` happens to be unset
 * (e.g. on Vercel preview deployments where the env var is only bound
 * to Production).  The error is still raised — but only on first query,
 * which page-level `try/catch` blocks handle gracefully.
 */

import postgres from "postgres";

let _sql: ReturnType<typeof postgres> | undefined;

export function getSql(): ReturnType<typeof postgres> {
  if (!_sql) {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL is not set");
    // `prepare: false` is required for pgBouncer transaction-pooling mode
    // (Neon's pooled endpoint).
    _sql = postgres(url, {
      prepare: false,
      ssl: "require",
      max: 5,
      idle_timeout: 20,
    });
  }
  return _sql;
}
