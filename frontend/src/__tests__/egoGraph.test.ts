import { describe, it, expect } from "vitest";
import {
  computeEgoSet,
  induceEdges,
  searchMatchIds,
  firstSearchMatch,
  topMovers,
  firstRootId,
  MOVER_MIN_DELTA_PTS,
} from "@/features/graph/egoGraph";

// v -> w -> x ->\
//                c -> d -> e -> f
// a -> b ------->/
const CHAIN = [
  { source: "a", target: "b" },
  { source: "b", target: "c" },
  { source: "c", target: "d" },
  { source: "d", target: "e" },
  { source: "e", target: "f" },
  { source: "x", target: "c" },
  { source: "w", target: "x" },
  { source: "v", target: "w" },
];

describe("computeEgoSet", () => {
  it("includes the center plus parents and children up to 2 hops", () => {
    const ego = computeEgoSet("c", CHAIN, 2);
    expect(ego).toEqual(new Set(["c", "b", "x", "a", "w", "d", "e"]));
  });

  it("excludes ancestors and descendants beyond the hop limit", () => {
    const ego = computeEgoSet("c", CHAIN, 2);
    expect(ego.has("v")).toBe(false); // 3 hops up
    expect(ego.has("f")).toBe(false); // 3 hops down
  });

  it("respects a 1-hop limit", () => {
    expect(computeEgoSet("c", CHAIN, 1)).toEqual(new Set(["c", "b", "x", "d"]));
  });

  it("does not pull in a parent's other children (directional walks only)", () => {
    // p -> c1, p -> sibling: sibling is not in c1's ego set.
    const edges = [
      { source: "p", target: "c1" },
      { source: "p", target: "sibling" },
    ];
    const ego = computeEgoSet("c1", edges, 2);
    expect(ego).toEqual(new Set(["c1", "p"]));
  });

  it("returns only the center for an isolated node", () => {
    expect(computeEgoSet("lone", CHAIN, 2)).toEqual(new Set(["lone"]));
  });

  it("ignores self-loops", () => {
    const ego = computeEgoSet("a", [{ source: "a", target: "a" }], 2);
    expect(ego).toEqual(new Set(["a"]));
  });
});

describe("induceEdges", () => {
  it("keeps only edges with both endpoints inside the set", () => {
    const ids = new Set(["b", "c", "d"]);
    expect(induceEdges(ids, CHAIN)).toEqual([
      { source: "b", target: "c" },
      { source: "c", target: "d" },
    ]);
  });

  it("returns nothing for a singleton set", () => {
    expect(induceEdges(new Set(["c"]), CHAIN)).toEqual([]);
  });
});

const NODES = [
  { id: "m1", title: "ETH Price > $3000" },
  { id: "m2", title: "BTC > $100K" },
  { id: "m3", title: "Fed cuts rates" },
  { id: "m4", title: "eth staking yield falls" },
];

describe("searchMatchIds", () => {
  it("returns null (no active search) for empty or blank queries", () => {
    expect(searchMatchIds("", NODES)).toBeNull();
    expect(searchMatchIds("   ", NODES)).toBeNull();
  });

  it("matches case-insensitive substrings of titles", () => {
    expect(searchMatchIds("eth", NODES)).toEqual(new Set(["m1", "m4"]));
    expect(searchMatchIds("BTC", NODES)).toEqual(new Set(["m2"]));
    expect(searchMatchIds("FED CUTS", NODES)).toEqual(new Set(["m3"]));
  });

  it("returns an empty set when nothing matches", () => {
    expect(searchMatchIds("zzz", NODES)).toEqual(new Set());
  });

  it("trims surrounding whitespace before matching", () => {
    expect(searchMatchIds("  btc  ", NODES)).toEqual(new Set(["m2"]));
  });
});

describe("firstSearchMatch", () => {
  it("returns the first match in node order", () => {
    expect(firstSearchMatch("eth", NODES)).toBe("m1");
  });

  it("returns null for blank queries or no matches", () => {
    expect(firstSearchMatch("", NODES)).toBeNull();
    expect(firstSearchMatch("zzz", NODES)).toBeNull();
  });
});

describe("topMovers", () => {
  it("orders by absolute delta descending, mixing signs", () => {
    const movers = topMovers([
      { id: "a", deltaPts: 2.0 },
      { id: "b", deltaPts: -9.5 },
      { id: "c", deltaPts: 4.1 },
    ]);
    expect(movers.map((m) => m.id)).toEqual(["b", "c", "a"]);
  });

  it("caps the list at 5 by default", () => {
    const movers = topMovers(
      ["a", "b", "c", "d", "e", "f", "g"].map((id, i) => ({ id, deltaPts: i + 1 })),
    );
    expect(movers).toHaveLength(5);
    expect(movers.map((m) => m.id)).toEqual(["g", "f", "e", "d", "c"]);
  });

  it("excludes deltas below the in-graph label threshold", () => {
    const movers = topMovers([
      { id: "a", deltaPts: 0.04 },
      { id: "b", deltaPts: -0.04 },
      { id: "c", deltaPts: MOVER_MIN_DELTA_PTS },
    ]);
    expect(movers.map((m) => m.id)).toEqual(["c"]);
  });

  it("keeps input order on exact ties", () => {
    const movers = topMovers([
      { id: "a", deltaPts: -3 },
      { id: "b", deltaPts: 3 },
      { id: "c", deltaPts: 3 },
    ]);
    expect(movers.map((m) => m.id)).toEqual(["a", "b", "c"]);
  });

  it("honors a custom count", () => {
    const movers = topMovers(
      [
        { id: "a", deltaPts: 1 },
        { id: "b", deltaPts: 2 },
      ],
      1,
    );
    expect(movers.map((m) => m.id)).toEqual(["b"]);
  });

  it("returns an empty list for no deltas", () => {
    expect(topMovers([])).toEqual([]);
  });
});

describe("firstRootId", () => {
  it("returns the first parentless node in input order", () => {
    expect(firstRootId(["b", "a", "v"], [{ source: "a", target: "b" }])).toBe("a");
  });

  it("falls back to the first node when every node has a parent (cycle)", () => {
    const ids = ["x", "y"];
    const edges = [
      { source: "x", target: "y" },
      { source: "y", target: "x" },
    ];
    expect(firstRootId(ids, edges)).toBe("x");
  });

  it("returns null for an empty graph", () => {
    expect(firstRootId([], [])).toBeNull();
  });

  it("ignores edges whose parent is outside the node set", () => {
    expect(firstRootId(["b"], [{ source: "a", target: "b" }])).toBe("b");
  });
});
