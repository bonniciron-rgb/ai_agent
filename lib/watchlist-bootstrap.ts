/**
 * Bootstrap the `watchlistticker` table from `config/watchlist.yaml`
 * the first time the Watchlist UI is opened.
 *
 * Mirrors `bootstrap_from_yaml()` in src/ai_agent/db/watchlist_store.py.
 *
 * No-op once any rows exist in the table.
 */

import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import { getSql } from "./db";

interface YamlEntry {
  symbol: string;
  sector?: string;
  notes?: string;
  tags?: string[];
}

interface WatchlistConfig {
  entries?: YamlEntry[];
}

export async function bootstrapWatchlistFromYaml(): Promise<number> {
  const sql = getSql();

  const [{ count }] = await sql<{ count: number }[]>`
    SELECT COUNT(*)::int AS count FROM watchlistticker
  `;
  if (count > 0) return 0;

  const cfgPath = path.join(process.cwd(), "config", "watchlist.yaml");
  if (!fs.existsSync(cfgPath)) return 0;

  const cfg = yaml.load(fs.readFileSync(cfgPath, "utf8")) as WatchlistConfig;
  const entries = (cfg?.entries ?? []).filter((e) => e?.symbol);
  if (entries.length === 0) return 0;

  for (const e of entries) {
    const symbol = e.symbol.trim().toUpperCase();
    if (!symbol) continue;
    await sql`
      INSERT INTO watchlistticker (symbol, sector, notes, tags_json, paused, added_at, updated_at)
      VALUES (
        ${symbol},
        ${e.sector ?? null},
        ${e.notes ?? null},
        ${JSON.stringify(e.tags ?? [])},
        false,
        NOW(),
        NOW()
      )
      ON CONFLICT (symbol) DO NOTHING
    `;
  }

  return entries.length;
}
