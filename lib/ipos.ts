/**
 * Finnhub IPO calendar — recent and upcoming US IPOs (emerging companies).
 *
 * The IPO list moves slowly, so the Finnhub response is cached for 6h.
 * Requires FINNHUB_API_KEY; absent it the page degrades gracefully.
 */

const KEY = process.env.FINNHUB_API_KEY || "";
const REVALIDATE = 6 * 60 * 60; // 6 hours

export interface Ipo {
  symbol: string;
  name: string;
  date: string; // YYYY-MM-DD
  exchange: string;
  status: string; // expected | priced | filed | withdrawn
  price: string; // price or range, as Finnhub reports it
  shares: number;
  totalValue: number;
}

export interface IpoCalendar {
  ipos: Ipo[]; // sorted newest/upcoming first
  configured: boolean;
  error?: string;
}

function fmtDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export async function getIpoCalendar(): Promise<IpoCalendar> {
  if (!KEY) return { ipos: [], configured: false };

  const now = new Date();
  const from = new Date(now);
  from.setDate(from.getDate() - 30);
  const to = new Date(now);
  to.setDate(to.getDate() + 60);

  const url =
    `https://finnhub.io/api/v1/calendar/ipo` +
    `?from=${fmtDate(from)}&to=${fmtDate(to)}&token=${KEY}`;

  try {
    const res = await fetch(url, { next: { revalidate: REVALIDATE } });
    if (!res.ok)
      return { ipos: [], configured: true, error: `Finnhub ${res.status}` };

    const body = (await res.json()) as {
      ipoCalendar?: {
        symbol?: string;
        name?: string;
        date?: string;
        exchange?: string;
        status?: string;
        price?: string;
        numberOfShares?: number;
        totalSharesValue?: number;
      }[];
    };

    const ipos: Ipo[] = (body.ipoCalendar ?? []).map((r) => ({
      symbol: r.symbol ?? "",
      name: r.name ?? "—",
      date: r.date ?? "",
      exchange: r.exchange ?? "",
      status: r.status ?? "",
      price: r.price ?? "",
      shares: r.numberOfShares ?? 0,
      totalValue: r.totalSharesValue ?? 0,
    }));
    ipos.sort((a, b) => b.date.localeCompare(a.date));
    return { ipos, configured: true };
  } catch (e) {
    return {
      ipos: [],
      configured: true,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}
