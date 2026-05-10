/**
 * Bootstrap the `signalchannel` table from `config/external_signals.yaml`
 * the first time the Signals UI is opened.
 *
 * Mirrors `bootstrap_from_yaml()` in
 * `src/ai_agent/external_signals/channel_store.py` — without it, the UI
 * shows an empty list until the Python signals-ingest workflow runs once,
 * which is confusing for new users.
 *
 * No-op once any rows exist in the table.
 */

import fs from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import { getSql } from "./db";

interface ChannelsConfig {
  channels?: string[];
}

export async function bootstrapSignalChannelsFromYaml(): Promise<number> {
  const sql = getSql();

  const [{ count }] = await sql<{ count: number }[]>`
    SELECT COUNT(*)::int AS count FROM signalchannel
  `;
  if (count > 0) return 0;

  const cfgPath = path.join(process.cwd(), "config", "external_signals.yaml");
  if (!fs.existsSync(cfgPath)) return 0;

  const cfg = yaml.load(fs.readFileSync(cfgPath, "utf8")) as ChannelsConfig;
  const handles = (cfg?.channels ?? [])
    .map((h) => h.trim())
    .filter((h) => h.length > 0)
    .map((h) => (h.startsWith("@") ? h : `@${h}`));

  if (handles.length === 0) return 0;

  for (const handle of handles) {
    await sql`
      INSERT INTO signalchannel (handle, paused, added_at)
      VALUES (${handle}, false, NOW())
      ON CONFLICT (handle) DO NOTHING
    `;
  }

  return handles.length;
}
