import { describe, it, expect } from "vitest";
import { deriveEdgesFromCliques, mergeEdges, remapEdgesToMarketIds } from "@/features/graph/deriveEdges";

describe("deriveEdgesFromCliques", () => {
  it("returns empty array for empty cliques", () => {
    expect(deriveEdgesFromCliques([])).toEqual([]);
  });

  it("returns no edges for single-node cliques", () => {
    const result = deriveEdgesFromCliques([{ id: "c1", nodes: ["a"], size: 1, states: 2 }]);
    expect(result).toEqual([]);
  });

  it("derives edges from a 2-node clique", () => {
    const result = deriveEdgesFromCliques([
      { id: "c1", nodes: ["a", "b"], size: 2, states: 4 },
    ]);
    expect(result).toEqual([{ source: "a", target: "b" }]);
  });

  it("derives all pairs from a 3-node clique", () => {
    const result = deriveEdgesFromCliques([
      { id: "c1", nodes: ["a", "b", "c"], size: 3, states: 8 },
    ]);
    expect(result).toHaveLength(3);
    expect(result).toEqual([
      { source: "a", target: "b" },
      { source: "a", target: "c" },
      { source: "b", target: "c" },
    ]);
  });

  it("deduplicates edges across cliques", () => {
    const result = deriveEdgesFromCliques([
      { id: "c1", nodes: ["a", "b"], size: 2, states: 4 },
      { id: "c2", nodes: ["b", "a"], size: 2, states: 4 },
    ]);
    expect(result).toHaveLength(1);
  });
});

describe("mergeEdges", () => {
  it("merges conditional edges with clique edges without duplicates", () => {
    const cliqueEdges = [{ source: "a", target: "b" }];
    const conditionalEdges = [
      { from: "a", to: "b" },  // duplicate
      { from: "c", to: "d" },  // new
    ];
    const result = mergeEdges(cliqueEdges, conditionalEdges);
    expect(result).toHaveLength(2);
    expect(result[1]).toEqual({ source: "c", target: "d" });
  });

  it("handles empty conditional edges", () => {
    const cliqueEdges = [{ source: "a", target: "b" }];
    const result = mergeEdges(cliqueEdges);
    expect(result).toHaveLength(1);
  });
});

describe("remapEdgesToMarketIds", () => {
  const markets = [
    { id: "m1", variableId: "var_alpha" },
    { id: "m2", variableId: "var_beta" },
    { id: "m3", variableId: "var_gamma" },
  ];

  it("maps variableId endpoints to market ids", () => {
    const result = remapEdgesToMarketIds(
      [{ source: "var_alpha", target: "var_beta" }],
      markets,
    );
    expect(result).toEqual([{ source: "m1", target: "m2" }]);
  });

  it("passes through endpoints already in market-id space", () => {
    const result = remapEdgesToMarketIds([{ source: "m1", target: "m3" }], markets);
    expect(result).toEqual([{ source: "m1", target: "m3" }]);
  });

  it("handles mixed id spaces on one edge", () => {
    const result = remapEdgesToMarketIds([{ source: "var_alpha", target: "m2" }], markets);
    expect(result).toEqual([{ source: "m1", target: "m2" }]);
  });

  it("drops edges with endpoints in neither id space", () => {
    const result = remapEdgesToMarketIds(
      [
        { source: "var_alpha", target: "unknown_variable" },
        { source: "var_beta", target: "var_gamma" },
      ],
      markets,
    );
    expect(result).toEqual([{ source: "m2", target: "m3" }]);
  });

  it("deduplicates edges that collapse to the same market pair", () => {
    const result = remapEdgesToMarketIds(
      [
        { source: "var_alpha", target: "var_beta" },
        { source: "m2", target: "m1" },
      ],
      markets,
    );
    expect(result).toHaveLength(1);
  });

  it("works without variableId metadata (snapshot markets)", () => {
    const result = remapEdgesToMarketIds(
      [{ source: "m1", target: "m2" }],
      [{ id: "m1" }, { id: "m2" }],
    );
    expect(result).toEqual([{ source: "m1", target: "m2" }]);
  });
});
