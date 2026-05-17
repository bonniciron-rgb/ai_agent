/**
 * Reddit retail-buzz tracker — most-discussed tickers on investing subreddits.
 *
 * Raw subreddit chatter is extremely noisy, so several filters are applied on
 * top of the raw mentions:
 *   1. Ticker candidates are validated against the SEC ticker universe.
 *   2. Common-word / slang false positives ($DD, YOLO, CEO…) are dropped.
 *   3. One-off mentions are discarded (a real trend needs repetition).
 *   4. Ranking is engagement-weighted (upvotes + comments, log-damped) so a
 *      handful of low-effort posts can't manufacture a "trend".
 *
 * This is a retail-SENTIMENT signal — momentum / awareness, not conviction.
 */

const UA = "ai-trading-agent/1.0 (stock buzz tracker)";
const REVALIDATE = 6 * 60 * 60; // 6 hours
const SUBREDDITS = ["wallstreetbets", "stocks", "StockMarket"];
const MIN_MENTIONS = 3; // discard one-off chatter
const MAX_ROWS = 15;

// Uppercase words that look like tickers but are slang / abbreviations.
const STOPWORDS = new Set([
  "DD",
  "YOLO",
  "FOMO",
  "FUD",
  "WSB",
  "CEO",
  "CFO",
  "COO",
  "IPO",
  "ETF",
  "USA",
  "USD",
  "GDP",
  "FED",
  "SEC",
  "IRS",
  "ATH",
  "ATL",
  "EOD",
  "EPS",
  "OTM",
  "ITM",
  "IMO",
  "IMHO",
  "TLDR",
  "EDIT",
  "AKA",
  "ELI",
  "NSFW",
  "AI",
  "EV",
  "OP",
  "HODL",
  "LOL",
  "LMAO",
  "WTF",
  "THE",
  "AND",
  "FOR",
  "ALL",
  "ARE",
  "BUT",
  "CAN",
  "NOW",
  "NEW",
  "ONE",
  "OUT",
  "BUY",
  "SELL",
  "HOLD",
  "CALL",
  "PUT",
  "BULL",
  "BEAR",
  "CASH",
  "LOSS",
  "GAIN",
  "RISK",
  "WSJ",
  "NYSE",
  "YTD",
  "EOY",
  "ER",
  "PT",
  "TP",
  "SL",
  "IV",
  "FD",
]);

export interface BuzzTicker {
  ticker: string;
  company: string;
  mentions: number;
  buzzScore: number;
  tier: "strong" | "moderate";
}

export interface RedditBuzz {
  tickers: BuzzTicker[];
  postsScanned: number;
  error?: string;
}

interface RedditPost {
  title?: string;
  selftext?: string;
  score?: number;
  num_comments?: number;
}

/** SEC ticker universe — used to reject candidates that aren't real tickers. */
async function tickerUniverse(): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  try {
    const res = await fetch("https://www.sec.gov/files/company_tickers.json", {
      headers: { "User-Agent": UA },
      next: { revalidate: 24 * 60 * 60 },
    });
    if (!res.ok) return map;
    const data = (await res.json()) as Record<
      string,
      { ticker?: string; title?: string }
    >;
    for (const row of Object.values(data)) {
      if (row.ticker) {
        map.set(row.ticker.toUpperCase(), row.title ?? row.ticker);
      }
    }
  } catch {
    /* validation simply disabled if EDGAR is unreachable */
  }
  return map;
}

async function fetchSubreddit(sub: string): Promise<RedditPost[]> {
  try {
    const res = await fetch(
      `https://www.reddit.com/r/${sub}/hot.json?limit=100`,
      {
        headers: { "User-Agent": UA },
        next: { revalidate: REVALIDATE },
      },
    );
    if (!res.ok) return [];
    const body = (await res.json()) as {
      data?: { children?: { data?: RedditPost }[] };
    };
    return (body.data?.children ?? []).map((c) => c.data ?? {});
  } catch {
    return [];
  }
}

/** Tickers mentioned in one post — a set, so a post counts once per ticker. */
function extractTickers(
  text: string,
  universe: Map<string, string>,
): Set<string> {
  const found = new Set<string>();
  // Cashtags ($NVDA) are explicit — trusted without universe validation.
  for (const m of text.matchAll(/\$([A-Za-z]{1,5})\b/g)) {
    const t = m[1].toUpperCase();
    if (!STOPWORDS.has(t)) found.add(t);
  }
  // Bare uppercase words — only if a real ticker and not slang.
  for (const m of text.matchAll(/\b[A-Z]{2,5}\b/g)) {
    const t = m[0];
    if (STOPWORDS.has(t) || !universe.has(t)) continue;
    found.add(t);
  }
  return found;
}

export async function getRedditBuzz(): Promise<RedditBuzz> {
  const universe = await tickerUniverse();
  const posts = (await Promise.all(SUBREDDITS.map(fetchSubreddit))).flat();
  if (posts.length === 0) {
    return { tickers: [], postsScanned: 0, error: "Reddit is unreachable" };
  }

  const agg = new Map<string, { mentions: number; score: number }>();
  for (const post of posts) {
    const found = extractTickers(
      `${post.title ?? ""} ${post.selftext ?? ""}`,
      universe,
    );
    // Engagement weight — log-damped so one viral post can't dominate.
    const weight =
      1 +
      Math.log10(1 + Math.max(0, post.score ?? 0)) +
      Math.log10(1 + Math.max(0, post.num_comments ?? 0));
    for (const t of found) {
      const cur = agg.get(t) ?? { mentions: 0, score: 0 };
      cur.mentions += 1;
      cur.score += weight;
      agg.set(t, cur);
    }
  }

  const ranked = [...agg.entries()]
    .filter(([, v]) => v.mentions >= MIN_MENTIONS)
    .sort((a, b) => b[1].score - a[1].score)
    .slice(0, MAX_ROWS);

  const topScore = ranked[0]?.[1].score ?? 0;
  const tickers: BuzzTicker[] = ranked.map(([ticker, v]) => ({
    ticker,
    company: universe.get(ticker) ?? "—",
    mentions: v.mentions,
    buzzScore: Math.round(v.score * 10) / 10,
    // "strong" = a genuine cluster of engaged discussion, not the long tail.
    tier: v.score >= 0.5 * topScore ? "strong" : "moderate",
  }));

  return { tickers, postsScanned: posts.length };
}
