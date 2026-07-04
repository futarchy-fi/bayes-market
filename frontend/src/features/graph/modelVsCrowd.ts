/**
 * Pure ranking + formatting helpers for the model-vs-crowd panel: which
 * markets disagree most with an external anchor (Metaculus/Manifold) or with
 * the futarchy team's own model-implied prior (ftmImplied). No DOM, no
 * React — everything here is testable with plain data.
 */

import type { MarketAnchorSource, MarketSummary } from "@/lib/api/types";

/** Short tag shown next to the reference probability in a row. */
export type ReferenceTag = "M" | "F" | "FTM";

const ANCHOR_TAG: Record<MarketAnchorSource, ReferenceTag> = {
  metaculus: "M",
  manifold: "F",
};

export interface ModelVsCrowdRow {
  id: string;
  title: string;
  /** Current market price, 0-1. */
  priceP: number;
  /** Reference probability being compared against, 0-1. */
  referenceP: number;
  referenceTag: ReferenceTag;
  /** (priceP - referenceP) in percentage points; signed. */
  gapPts: number;
}

/**
 * The market's current headline price: the "yes" marginal if present, else
 * the first outcome's marginal in object-insertion order. Same convention
 * used elsewhere for MarketSummary-shaped data (e.g. MarketList's PriceBar).
 */
export function currentPrice(market: MarketSummary): number | null {
  const marginals = market.marginals;
  if (!marginals) return null;
  const p = marginals["yes"] ?? Object.values(marginals)[0];
  return typeof p === "number" ? p : null;
}

function rankByAbsGap(rows: ModelVsCrowdRow[], count: number): ModelVsCrowdRow[] {
  return rows
    .map((row, i) => ({ row, i }))
    .sort((a, b) => Math.abs(b.row.gapPts) - Math.abs(a.row.gapPts) || a.i - b.i)
    .slice(0, Math.max(0, count))
    .map((x) => x.row);
}

/** Top `count` markets by |price - anchor.value|, largest gap first. */
export function topAnchorGaps(markets: MarketSummary[], count = 6): ModelVsCrowdRow[] {
  const rows: ModelVsCrowdRow[] = [];
  for (const m of markets) {
    const p = currentPrice(m);
    if (p == null || !m.anchor) continue;
    rows.push({
      id: m.id,
      title: m.title,
      priceP: p,
      referenceP: m.anchor.value,
      referenceTag: ANCHOR_TAG[m.anchor.source],
      gapPts: (p - m.anchor.value) * 100,
    });
  }
  return rankByAbsGap(rows, count);
}

/** Top `count` markets by |price - ftmImplied|, largest gap first. */
export function topFtmGaps(markets: MarketSummary[], count = 6): ModelVsCrowdRow[] {
  const rows: ModelVsCrowdRow[] = [];
  for (const m of markets) {
    const p = currentPrice(m);
    if (p == null || m.ftmImplied == null) continue;
    rows.push({
      id: m.id,
      title: m.title,
      priceP: p,
      referenceP: m.ftmImplied,
      referenceTag: "FTM",
      gapPts: (p - m.ftmImplied) * 100,
    });
  }
  return rankByAbsGap(rows, count);
}

/** Whether any market carries either comparable field; when false, render nothing. */
export function hasModelVsCrowdData(markets: MarketSummary[]): boolean {
  return markets.some((m) => m.anchor != null || m.ftmImplied != null);
}

/** Percentage string with one decimal, e.g. 0.628 -> "62.8%". */
export function formatPct(p: number): string {
  return `${(p * 100).toFixed(1)}%`;
}

/**
 * Same ▲/▼ + magnitude convention used for deltas in BeliefFlowGraph:
 * up-triangle for a positive gap (price above reference), down-triangle
 * otherwise, magnitude to one decimal place, unsigned.
 */
export function formatGap(gapPts: number): { symbol: "▲" | "▼"; magnitude: string } {
  return { symbol: gapPts >= 0 ? "▲" : "▼", magnitude: Math.abs(gapPts).toFixed(1) };
}

/** Truncates to `maxChars`, appending an ellipsis when it had to cut. */
export function truncateTitle(title: string, maxChars = 42): string {
  if (title.length <= maxChars) return title;
  return `${title.slice(0, Math.max(1, maxChars - 1))}…`;
}
