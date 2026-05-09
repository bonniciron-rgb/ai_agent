/**
 * Tiny pure functions for the proposal-detail snapshot.
 *
 * These run server-side over decimal-strings returned by `getRecentBars()`.
 * No external dependencies.
 */

import type { Bar } from "./queries";

export interface IndicatorSnapshot {
  rsi14: number | null;
  sma50: number | null;
  latestClose: number | null;
  latestVolume: number | null;
  volumeVs20Avg: number | null; // ratio: latest / 20-day average
}

export function computeIndicators(bars: Bar[]): IndicatorSnapshot {
  const closes = bars.map((b) => Number(b.close));
  const volumes = bars.map((b) => Number(b.volume));
  return {
    rsi14: rsi(closes, 14),
    sma50: sma(closes, 50),
    latestClose: closes.length ? closes[closes.length - 1] : null,
    latestVolume: volumes.length ? volumes[volumes.length - 1] : null,
    volumeVs20Avg: volumeVsAvg(volumes, 20),
  };
}

function sma(values: number[], period: number): number | null {
  if (values.length < period) return null;
  const window = values.slice(-period);
  return window.reduce((a, b) => a + b, 0) / period;
}

/** Wilder-smoothed RSI. Returns null if not enough data. */
function rsi(closes: number[], period: number): number | null {
  if (closes.length < period + 1) return null;
  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gains += diff;
    else losses += -diff;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;
  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = diff > 0 ? diff : 0;
    const loss = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
  }
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

function volumeVsAvg(volumes: number[], period: number): number | null {
  if (volumes.length < period + 1) return null;
  const recent = volumes.slice(-period - 1, -1); // exclude latest
  const avg = recent.reduce((a, b) => a + b, 0) / recent.length;
  if (avg === 0) return null;
  return volumes[volumes.length - 1] / avg;
}

/**
 * Render closing prices as an SVG path string normalised into a 0..height box.
 * Returns null if fewer than 2 points.
 */
export interface SparklineGeometry {
  path: string;
  width: number;
  height: number;
  min: number;
  max: number;
  /** Y-coordinate (in svg space) for `priceLine`, or null if outside range. */
  priceLineY: number | null;
}

export function buildSparkline(
  closes: number[],
  width = 600,
  height = 100,
  priceLine: number | null = null,
): SparklineGeometry | null {
  if (closes.length < 2) return null;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const stepX = width / (closes.length - 1);
  const path = closes
    .map((c, i) => {
      const x = i * stepX;
      const y = height - ((c - min) / range) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  let priceLineY: number | null = null;
  if (priceLine !== null && priceLine >= min && priceLine <= max) {
    priceLineY = height - ((priceLine - min) / range) * height;
  }
  return { path, width, height, min, max, priceLineY };
}
