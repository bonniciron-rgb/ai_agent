"use client";

import { useEffect, useRef } from "react";
import type { Time } from "lightweight-charts";

interface Props {
  data: { date: string; cost: number }[];
}

export default function DailyCostChart({ data }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || data.length === 0) return;

    let cleanup: (() => void) | undefined;

    import("lightweight-charts").then((lc) => {
      const chart = lc.createChart(ref.current!, {
        height: 220,
        autoSize: true,
        layout: { background: { color: "#09090b" }, textColor: "#a1a1aa" },
        grid: { vertLines: { color: "#27272a" }, horzLines: { color: "#27272a" } },
        timeScale: { borderColor: "#27272a", timeVisible: false },
        rightPriceScale: { borderColor: "#27272a" },
      });

      const series = chart.addSeries(lc.HistogramSeries, {
        color: "#818cf8",
        priceFormat: {
          type: "custom",
          minMove: 0.0001,
          formatter: (p: number) => `$${p.toFixed(2)}`,
        },
      });

      series.setData(
        data.map((d) => ({
          time: d.date as Time,
          value: d.cost,
        })),
      );

      chart.timeScale().fitContent();

      cleanup = () => chart.remove();
    });

    return () => cleanup?.();
  }, [data]);

  return <div ref={ref} />;
}
