/**
 * Retail-buzz tracker — most-discussed tickers across investing subreddits.
 *
 * Reddit blocks unauthenticated requests from datacenter IPs (Vercel), so the
 * buzz data is sourced from ApeWisdom (apewisdom.io), which aggregates ticker
 * mentions across r/wallstreetbets, r/stocks and related subreddits.
 *
 * Filtering logic on top of the raw feed:
 *   - low-traction tickers (< MIN_MENTIONS) are discarded;
 *   - ranking is engagement-weighted (mentions x log-upvotes), so a quiet
 *     ticker with a few loud posts can't outrank a genuinely busy one;
 *   - each ticker is classed rising / steady / fading by comparing mentions
 *     to 24h ago — a momentum filter, not just a popularity snapshot.
 *
 * This is a retail-SENTIMENT signal — momentum / awareness, not conviction.
 */

const API = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/1";
const REVALIDATE = 3 * 60 * 60; // 3h — ApeWisdom refreshes roughly hourly
const MIN_MENTIONS = 5;
const MAX_ROWS = 15;
const RISING = 0.25; // +25% mentions vs 24h ago
const FADING = -0.25;

export type BuzzTier = "rising" | "steady" | "fading";

export interface BuzzTicker {
  ticker: string;
  company: string;
  mentions: number;
  mentions24hAgo: number;
  momentumPct: number; // change in mentions vs 24h ago
  tier: BuzzTier;
}

export interface RedditBuzz {
  tickers: BuzzTicker[];
  error?: string;
}

interface ApeRow {
  ticker?: string;
  name?: string;
  mentions?: number | string;
  upvotes?: number | string;
  mentions_24h_ago?: number | string;
}

function num(v: number | string | undefined): number {
  const n = typeof v === "string" ? Number(v) : (v ?? 0);
  return Number.isFinite(n) ? n : 0;
}

export async function getRedditBuzz(): Promise<RedditBuzz> {
  try {
    const res = await fetch(API, {
      headers: { "User-Agent": "ai-trading-agent/1.0 (buzz tracker)" },
      next: { revalidate: REVALIDATE },
    });
    if (!res.ok) {
      return { tickers: [], error: `buzz source returned ${res.status}` };
    }

    const body = (await res.json()) as { results?: ApeRow[] };
    const ranked = (body.results ?? [])
      .map((r) => {
        const mentions = num(r.mentions);
        const prev = num(r.mentions_24h_ago);
        const upvotes = num(r.upvotes);
        const momentumPct =
          prev > 0 ? (mentions - prev) / prev : mentions > 0 ? 1 : 0;
        // Engagement-weighted: mentions scaled by how upvoted the chatter is.
        const buzzScore = mentions * (1 + Math.log10(1 + upvotes));
        return {
          ticker: (r.ticker ?? "").toUpperCase(),
          company: r.name?.trim() || "—",
          mentions,
          mentions24hAgo: prev,
          momentumPct,
          buzzScore,
        };
      })
      .filter((t) => t.ticker && t.mentions >= MIN_MENTIONS)
      .sort((a, b) => b.buzzScore - a.buzzScore)
      .slice(0, MAX_ROWS);

    const tickers: BuzzTicker[] = ranked.map((t) => ({
      ticker: t.ticker,
      company: t.company,
      mentions: t.mentions,
      mentions24hAgo: t.mentions24hAgo,
      momentumPct: t.momentumPct,
      tier:
        t.momentumPct >= RISING
          ? "rising"
          : t.momentumPct <= FADING
            ? "fading"
            : "steady",
    }));
    return { tickers };
  } catch (e) {
    return { tickers: [], error: e instanceof Error ? e.message : String(e) };
  }
}
