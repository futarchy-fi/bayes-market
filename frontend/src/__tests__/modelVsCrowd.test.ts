import { describe, it, expect } from "vitest";
import {
  currentPrice,
  topAnchorGaps,
  topFtmGaps,
  hasModelVsCrowdData,
  formatPct,
  formatGap,
  truncateTitle,
} from "@/features/graph/modelVsCrowd";
import type { MarketSummary } from "@/lib/api/types";

function market(overrides: Partial<MarketSummary> & { id: string }): MarketSummary {
  return {
    title: overrides.title ?? overrides.id,
    status: "active",
    liquidity: 0,
    volume: 0,
    expires_at: "2026-12-31T23:59:59Z",
    ...overrides,
  };
}

describe("currentPrice", () => {
  it("prefers the yes marginal", () => {
    expect(currentPrice(market({ id: "m1", marginals: { yes: 0.62, no: 0.38 } }))).toBe(0.62);
  });

  it("falls back to the first marginal in object order when there is no yes", () => {
    expect(currentPrice(market({ id: "m1", marginals: { long: 0.3, short: 0.7 } }))).toBe(0.3);
  });

  it("returns null when marginals are absent", () => {
    expect(currentPrice(market({ id: "m1" }))).toBeNull();
  });
});

describe("topAnchorGaps", () => {
  it("ranks by |price - anchor.value| descending", () => {
    const markets = [
      market({ id: "a", title: "A", marginals: { yes: 0.5 }, anchor: { source: "metaculus", ref: "1", url: "u", value: 0.52, fetchedAt: "t" } }), // |gap| = 2.0
      market({ id: "b", title: "B", marginals: { yes: 0.9 }, anchor: { source: "manifold", ref: "2", url: "u", value: 0.4, fetchedAt: "t" } }),
      market({ id: "c", title: "C", marginals: { yes: 0.3 }, anchor: { source: "metaculus", ref: "3", url: "u", value: 0.29, fetchedAt: "t" } }),
    ];
    const rows = topAnchorGaps(markets);
    expect(rows.map((r) => r.id)).toEqual(["b", "a", "c"]);
  });

  it("tags metaculus as M and manifold as F", () => {
    const markets = [
      market({ id: "a", marginals: { yes: 0.5 }, anchor: { source: "metaculus", ref: "1", url: "u", value: 0.4, fetchedAt: "t" } }),
      market({ id: "b", marginals: { yes: 0.5 }, anchor: { source: "manifold", ref: "2", url: "u", value: 0.3, fetchedAt: "t" } }),
    ];
    const rows = topAnchorGaps(markets);
    expect(rows.find((r) => r.id === "a")?.referenceTag).toBe("M");
    expect(rows.find((r) => r.id === "b")?.referenceTag).toBe("F");
  });

  it("skips markets with no anchor or no readable price", () => {
    const markets = [
      market({ id: "a", marginals: { yes: 0.5 } }),
      market({ id: "b", anchor: { source: "metaculus", ref: "1", url: "u", value: 0.4, fetchedAt: "t" } }),
      market({ id: "c", marginals: { yes: 0.5 }, anchor: { source: "metaculus", ref: "1", url: "u", value: 0.1, fetchedAt: "t" } }),
    ];
    expect(topAnchorGaps(markets).map((r) => r.id)).toEqual(["c"]);
  });

  it("caps at 6 by default and honors a custom count", () => {
    const markets = Array.from({ length: 10 }, (_, i) =>
      market({
        id: `m${i}`,
        marginals: { yes: 0.5 },
        anchor: { source: "metaculus", ref: String(i), url: "u", value: 0.5 - (i + 1) / 100, fetchedAt: "t" },
      }),
    );
    expect(topAnchorGaps(markets)).toHaveLength(6);
    expect(topAnchorGaps(markets, 3)).toHaveLength(3);
  });

  it("keeps input order on exact ties", () => {
    const markets = [
      market({ id: "a", marginals: { yes: 0.5 }, anchor: { source: "metaculus", ref: "1", url: "u", value: 0.4, fetchedAt: "t" } }),
      market({ id: "b", marginals: { yes: 0.5 }, anchor: { source: "metaculus", ref: "2", url: "u", value: 0.6, fetchedAt: "t" } }),
    ];
    // Both have |gap| == 10pts, opposite sign; input order should be preserved.
    expect(topAnchorGaps(markets).map((r) => r.id)).toEqual(["a", "b"]);
  });
});

describe("topFtmGaps", () => {
  it("ranks by |price - ftmImplied| descending and tags FTM", () => {
    const markets = [
      market({ id: "a", marginals: { yes: 0.2 }, ftmImplied: 0.21 }),
      market({ id: "b", marginals: { yes: 0.8 }, ftmImplied: 0.3 }),
    ];
    const rows = topFtmGaps(markets);
    expect(rows.map((r) => r.id)).toEqual(["b", "a"]);
    expect(rows.every((r) => r.referenceTag === "FTM")).toBe(true);
  });

  it("skips markets with no ftmImplied", () => {
    const markets = [market({ id: "a", marginals: { yes: 0.5 } })];
    expect(topFtmGaps(markets)).toEqual([]);
  });
});

describe("hasModelVsCrowdData", () => {
  it("is false when no market carries anchor or ftmImplied", () => {
    expect(hasModelVsCrowdData([market({ id: "a" }), market({ id: "b" })])).toBe(false);
  });

  it("is true when at least one market has an anchor", () => {
    expect(
      hasModelVsCrowdData([
        market({ id: "a" }),
        market({ id: "b", anchor: { source: "metaculus", ref: "1", url: "u", value: 0.5, fetchedAt: "t" } }),
      ]),
    ).toBe(true);
  });

  it("is true when at least one market has ftmImplied", () => {
    expect(hasModelVsCrowdData([market({ id: "a", ftmImplied: 0.4 })])).toBe(true);
  });

  it("is false for an empty list", () => {
    expect(hasModelVsCrowdData([])).toBe(false);
  });
});

describe("formatPct", () => {
  it("renders one decimal place", () => {
    expect(formatPct(0.628298)).toBe("62.8%");
    expect(formatPct(0)).toBe("0.0%");
    expect(formatPct(1)).toBe("100.0%");
  });
});

describe("formatGap", () => {
  it("uses an up-triangle for a positive gap", () => {
    expect(formatGap(3.14)).toEqual({ symbol: "▲", magnitude: "3.1" });
  });

  it("uses a down-triangle for a negative gap", () => {
    expect(formatGap(-3.14)).toEqual({ symbol: "▼", magnitude: "3.1" });
  });

  it("treats exactly zero as non-negative (up-triangle)", () => {
    expect(formatGap(0)).toEqual({ symbol: "▲", magnitude: "0.0" });
  });
});

describe("truncateTitle", () => {
  it("leaves short titles untouched", () => {
    expect(truncateTitle("Short title", 42)).toBe("Short title");
  });

  it("truncates long titles with an ellipsis", () => {
    const long = "A".repeat(50);
    const out = truncateTitle(long, 42);
    expect(out.length).toBe(42);
    expect(out.endsWith("…")).toBe(true);
  });
});
