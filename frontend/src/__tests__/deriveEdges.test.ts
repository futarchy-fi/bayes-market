import { describe, it, expect } from "vitest";
import { deriveEdgesFromCliques, mergeEdges } from "@/features/graph/deriveEdges";

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
