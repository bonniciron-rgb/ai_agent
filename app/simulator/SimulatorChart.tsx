"use client";

import { useEffect, useRef, useState } from "react";
import type { SimulatorBar, SimulatorProposal } from "@/lib/queries";
import type { Time, SeriesMarker } from "lightweight-charts";

// ─── Simulation engine ────────────────────────────────────────────────────

interface SimTrade {
  openDate: string;
  closeDate: string | null;
  openPrice: number;
  closePrice: number | null;
  shares: number;
  pnl: number | null;
}

interface SimResult {
  equityCurve: { time: string; value: number }[];
  trades: SimTrade[];
}

function runSimulation(
  bars: SimulatorBar[],
  proposals: SimulatorProposal[],
  initialCapital: number,
): SimResult {
  let cash = initialCapital;
  let shares = 0;
  let entryPrice = 0;
  const equityCurve: { time: string; value: number }[] = [];
  const trades: SimTrade[] = [];
  let openTrade: Omit<SimTrade, "closeDate" | "closePrice" | "pnl"> | null = null;

  const byDate = new Map<string, SimulatorProposal[]>();
  for (const p of proposals) {
    const arr = byDate.get(p.created_date) ?? [];
    arr.push(p);
    byDate.set(p.created_date, arr);
  }

  for (const bar of bars) {
    const dayProps = byDate.get(bar.trading_date) ?? [];

    for (const p of dayProps) {
      const nav = cash + shares * bar.open;

      if (p.side === "buy" && shares === 0 && cash > 0) {
        const target = Math.min(nav * 0.05, cash);
        const qty = Math.floor(target / p.limit_price);
        if (qty > 0) {
          cash -= qty * p.limit_price;
          shares = qty;
          entryPrice = p.limit_price;
          openTrade = { openDate: bar.trading_date, openPrice: p.limit_price, shares: qty };
        }
      } else if (p.side === "sell" && shares > 0) {
        const proceeds = shares * p.limit_price;
        const pnl = proceeds - shares * entryPrice;
        cash += proceeds;
        if (openTrade) {
          trades.push({ ...openTrade, closeDate: bar.trading_date, closePrice: p.limit_price, pnl });
        }
        shares = 0;
        openTrade = null;
      }
    }

    const nav = cash + shares * bar.close;
    equityCurve.push({ time: bar.trading_date, value: Math.round(nav * 100) / 100 });
  }

  return { equityCurve, trades };
}

// ─── Stats ────────────────────────────────────────────────────────────────

interface Stats {
  totalReturn: number;
  sharpe: number;
  maxDrawdown: number;
  winRate: number | null;
  tradeCount: number;
  finalValue: number;
}

function computeStats(curve: { value: number }[], trades: SimTrade[], initial: number): Stats {
  const vals = curve.map((c) => c.value);
  if (vals.length === 0) {
    return { totalReturn: 0, sharpe: 0, maxDrawdown: 0, winRate: null, tradeCount: 0, finalValue: initial };
  }

  const final = vals[vals.length - 1];
  const totalReturn = ((final - initial) / initial) * 100;

  const rets = vals.slice(1).map((v, i) => (v - vals[i]) / vals[i]);
  const mean = rets.reduce((a, b) => a + b, 0) / (rets.length || 1);
  const variance = rets.map((r) => (r - mean) ** 2).reduce((a, b) => a + b, 0) / (rets.length || 1);
  const std = Math.sqrt(variance);
  const sharpe = std > 0 ? (mean / std) * Math.sqrt(252) : 0;

  let peak = vals[0];
  let maxDD = 0;
  for (const v of vals) {
    if (v > peak) peak = v;
    const dd = peak > 0 ? (peak - v) / peak : 0;
    if (dd > maxDD) maxDD = dd;
  }

  const closed = trades.filter((t) => t.pnl !== null);
  const wins = closed.filter((t) => (t.pnl ?? 0) > 0).length;
  const winRate = closed.length > 0 ? (wins / closed.length) * 100 : null;

  return {
    totalReturn: Math.round(totalReturn * 10) / 10,
    sharpe: Math.round(sharpe * 100) / 100,
    maxDrawdown: Math.round(maxDD * 1000) / 10,
    winRate: winRate !== null ? Math.round(winRate * 10) / 10 : null,
    tradeCount: closed.length,
    finalValue: Math.round(final * 100) / 100,
  };
}

// ─── Marker colour ────────────────────────────────────────────────────────

function markerColor(status: string, side: string): string {
  if (status === "approved" || status === "executed") return side === "buy" ? "#22c55e" : "#ef4444";
  if (status === "rejected" || status === "expired") return "#71717a";
  return side === "buy" ? "#86efac" : "#fca5a5";
}

// ─── Chart component ──────────────────────────────────────────────────────

interface Props {
  bars: SimulatorBar[];
  proposals: SimulatorProposal[];
  initialCapital: number;
}

const CHART_OPTS = {
  layout: { background: { color: "#09090b" }, textColor: "#a1a1aa" },
  grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
  timeScale: { borderColor: "#27272a", timeVisible: true },
  rightPriceScale: { borderColor: "#27272a" },
};

export default function SimulatorChart({ bars, proposals, initialCapital }: Props) {
  const priceRef = useRef<HTMLDivElement>(null);
  const equityRef = useRef<HTMLDivElement>(null);
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    if (!priceRef.current || !equityRef.current || bars.length === 0) return;

    const { equityCurve, trades } = runSimulation(bars, proposals, initialCapital);
    setStats(computeStats(equityCurve, trades, initialCapital));

    // Dynamically import the canvas-based chart library
    import("lightweight-charts").then((lc) => {
      // ── Price / candlestick chart ─────────────────────────────────────
      const priceChart = lc.createChart(priceRef.current!, {
        ...CHART_OPTS,
        height: 360,
        autoSize: true,
      });

      const candles = priceChart.addSeries(lc.CandlestickSeries, {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
      });

      candles.setData(
        bars.map((b) => ({
          time: b.trading_date as Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        })),
      );

      // Filter proposal markers to dates that exist in bars
      const barDates = new Set(bars.map((b) => b.trading_date));
      const markers: SeriesMarker<Time>[] = proposals
        .filter((p) => barDates.has(p.created_date))
        .map((p) => ({
          time: p.created_date as Time,
          position: p.side === "buy" ? "belowBar" : "aboveBar",
          color: markerColor(p.status, p.side),
          shape: p.side === "buy" ? "arrowUp" : "arrowDown",
          text: `${p.side} ${p.status}`,
          size: 1,
        }));

      // v5 API: markers are a separate primitive, not a series method
      lc.createSeriesMarkers(candles, markers);
      priceChart.timeScale().fitContent();

      // ── Equity curve chart ────────────────────────────────────────────
      const equityChart = lc.createChart(equityRef.current!, {
        ...CHART_OPTS,
        height: 180,
        autoSize: true,
      });

      const line = equityChart.addSeries(lc.LineSeries, {
        color: "#818cf8",
        lineWidth: 2,
      });

      line.setData(
        equityCurve.map((e) => ({ time: e.time as Time, value: e.value })),
      );
      equityChart.timeScale().fitContent();

      // Sync time scales
      priceChart.timeScale().subscribeVisibleTimeRangeChange((range) => {
        if (range) equityChart.timeScale().setVisibleRange(range);
      });

      return () => {
        priceChart.remove();
        equityChart.remove();
      };
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, proposals, initialCapital]);

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatCard
            label="Total return"
            value={`${stats.totalReturn >= 0 ? "+" : ""}${stats.totalReturn}%`}
            positive={stats.totalReturn >= 0}
          />
          <StatCard label="Final value" value={`£${stats.finalValue.toLocaleString()}`} />
          <StatCard label="Sharpe" value={stats.sharpe.toFixed(2)} />
          <StatCard label="Max drawdown" value={`${stats.maxDrawdown}%`} negative={stats.maxDrawdown > 0} />
          <StatCard
            label={`Win rate (${stats.tradeCount} trades)`}
            value={stats.winRate !== null ? `${stats.winRate}%` : "—"}
          />
        </div>
      )}

      {/* Price chart */}
      <div className="rounded-lg border border-zinc-800 overflow-hidden">
        <p className="px-4 py-2 text-xs text-zinc-500 bg-zinc-900/40 border-b border-zinc-800">
          Price · ▲ buy proposal · ▼ sell proposal
        </p>
        <div ref={priceRef} />
      </div>

      {/* Equity curve */}
      <div className="rounded-lg border border-zinc-800 overflow-hidden">
        <p className="px-4 py-2 text-xs text-zinc-500 bg-zinc-900/40 border-b border-zinc-800">
          Hypothetical portfolio value (5% position cap, proposals as signals)
        </p>
        <div ref={equityRef} />
      </div>

      {bars.length === 0 && (
        <p className="text-sm text-zinc-500 mt-4">No OHLCV data for this symbol/period in the database.</p>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  positive,
  negative,
}: {
  label: string;
  value: string;
  positive?: boolean;
  negative?: boolean;
}) {
  const valueClass = positive
    ? "text-emerald-400"
    : negative
      ? "text-rose-400"
      : "text-zinc-100";
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className={`mt-1 text-lg font-semibold tabular-nums ${valueClass}`}>{value}</p>
    </div>
  );
}
