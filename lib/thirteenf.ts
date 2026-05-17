/**
 * SEC EDGAR 13F holdings fetcher — institutional "smart money" tracker.
 *
 * Pulls a fund manager's most recent 13F-HR filing (the quarterly disclosure
 * of long US-equity holdings) directly from EDGAR. 13F data only changes once
 * a quarter, so the EDGAR responses are cached for 6h via `next.revalidate`.
 */

const UA =
  process.env.EDGAR_USER_AGENT || "ai-trading-agent/1.0 (contact@example.com)";
const REVALIDATE = 6 * 60 * 60; // 6 hours — 13F data updates quarterly

export interface Manager {
  name: string;
  cik: string; // 10-digit zero-padded
}

export interface Holding {
  issuer: string;
  cusip: string;
  value: number; // USD, as reported in the filing
  shares: number;
  pct: number; // share of the manager's total 13F portfolio (0..1)
}

export interface Report {
  manager: string;
  cik: string;
  periodOfReport: string | null; // e.g. "2026-03-31"
  filedDate: string | null;
  totalValue: number;
  holdings: Holding[]; // merged by issuer, sorted by value desc
  error?: string;
}

/** Widely-followed institutional managers, by SEC CIK. */
export const MANAGERS: Manager[] = [
  { name: "Berkshire Hathaway — Warren Buffett", cik: "0001067983" },
  { name: "Scion Asset Management — Michael Burry", cik: "0001649339" },
  { name: "Pershing Square — Bill Ackman", cik: "0001336528" },
];

interface SubmissionsRecent {
  form?: string[];
  accessionNumber?: string[];
  reportDate?: string[];
  filingDate?: string[];
}

async function edgarJson<T>(url: string): Promise<T> {
  const res = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/json" },
    next: { revalidate: REVALIDATE },
  });
  if (!res.ok) throw new Error(`EDGAR ${res.status}`);
  return (await res.json()) as T;
}

async function edgarText(url: string): Promise<string> {
  const res = await fetch(url, {
    headers: { "User-Agent": UA },
    next: { revalidate: REVALIDATE },
  });
  if (!res.ok) throw new Error(`EDGAR ${res.status}`);
  return res.text();
}

const ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
};

/** Read one tag's text from an XML fragment (namespace-prefix tolerant). */
function tag(xml: string, name: string): string | null {
  const m = xml.match(new RegExp(`<(?:\\w+:)?${name}\\b[^>]*>([^<]*)<`, "i"));
  if (!m) return null;
  return m[1]
    .trim()
    .replace(/&(amp|lt|gt|quot|#39|apos);/g, (e) => ENTITIES[e] ?? e);
}

export async function getLatest13F(manager: Manager): Promise<Report> {
  const base: Report = {
    manager: manager.name,
    cik: manager.cik,
    periodOfReport: null,
    filedDate: null,
    totalValue: 0,
    holdings: [],
  };
  try {
    const subs = await edgarJson<{ filings?: { recent?: SubmissionsRecent } }>(
      `https://data.sec.gov/submissions/CIK${manager.cik}.json`,
    );
    const recent = subs.filings?.recent ?? {};
    const forms = recent.form ?? [];
    const idx = forms.findIndex((f) => f === "13F-HR" || f === "13F-HR/A");
    if (idx < 0) return { ...base, error: "no 13F-HR filing found" };

    const accession = recent.accessionNumber?.[idx] ?? "";
    const periodOfReport = recent.reportDate?.[idx] ?? null;
    const filedDate = recent.filingDate?.[idx] ?? null;
    const cikInt = String(Number(manager.cik));
    const dir = `https://www.sec.gov/Archives/edgar/data/${cikInt}/${accession.replace(/-/g, "")}`;

    const index = await edgarJson<{
      directory?: { item?: { name: string }[] };
    }>(`${dir}/index.json`);
    const infoFile = (index.directory?.item ?? []).find((it) =>
      /(?:info|information)table.*\.xml$/i.test(it.name),
    );
    if (!infoFile) {
      return {
        ...base,
        periodOfReport,
        filedDate,
        error: "no info table in filing",
      };
    }

    const xml = await edgarText(`${dir}/${infoFile.name}`);
    const blocks =
      xml.match(/<(?:\w+:)?infoTable\b[\s\S]*?<\/(?:\w+:)?infoTable>/gi) ?? [];

    // 13F lists each lot separately; merge by issuer (keyed on CUSIP).
    const merged = new Map<string, Holding>();
    for (const block of blocks) {
      const value = Number(tag(block, "value") ?? "0");
      if (!(value > 0)) continue;
      const issuer = tag(block, "nameOfIssuer") ?? "—";
      const cusip = tag(block, "cusip") ?? "";
      const shares = Number(tag(block, "sshPrnamt") ?? "0");
      const key = cusip || issuer;
      const prev = merged.get(key);
      if (prev) {
        prev.value += value;
        prev.shares += shares;
      } else {
        merged.set(key, { issuer, cusip, value, shares, pct: 0 });
      }
    }

    const holdings = [...merged.values()].sort((a, b) => b.value - a.value);
    const totalValue = holdings.reduce((s, h) => s + h.value, 0);
    for (const h of holdings) h.pct = totalValue > 0 ? h.value / totalValue : 0;

    return { ...base, periodOfReport, filedDate, totalValue, holdings };
  } catch (e) {
    return { ...base, error: e instanceof Error ? e.message : String(e) };
  }
}
