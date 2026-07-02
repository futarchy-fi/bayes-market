import { describe, it, expect } from "vitest";
import { layerByLongestPath, computeFlowLayout, wrapTitle } from "@/features/graph/flowLayout";

const CHAIN = [
  { source: "a", target: "b" },
  { source: "b", target: "c" },
];

describe("layerByLongestPath", () => {
  it("puts roots at layer 0 and children one past their deepest parent", () => {
    const layers = layerByLongestPath(["a", "b", "c"], CHAIN);
    expect(layers.get("a")).toBe(0);
    expect(layers.get("b")).toBe(1);
    expect(layers.get("c")).toBe(2);
  });

  it("uses the LONGEST path in a diamond (direct + indirect parent)", () => {
    // a -> b -> d, a -> d: d must sit past b, not beside it
    const layers = layerByLongestPath(["a", "b", "d"], [
      { source: "a", target: "b" },
      { source: "b", target: "d" },
      { source: "a", target: "d" },
    ]);
    expect(layers.get("d")).toBe(2);
  });

  it("places isolated nodes at layer 0", () => {
    const layers = layerByLongestPath(["a", "b", "lone"], [{ source: "a", target: "b" }]);
    expect(layers.get("lone")).toBe(0);
  });

  it("does not crash on a cycle; cyclic nodes land past the deepest layer", () => {
    const layers = layerByLongestPath(["a", "x", "y"], [
      { source: "x", target: "y" },
      { source: "y", target: "x" },
    ]);
    expect(layers.get("a")).toBe(0);
    expect(layers.get("x")).toBeGreaterThan(0);
    expect(layers.get("y")).toBeGreaterThan(0);
  });
});

describe("computeFlowLayout", () => {
  it("flows layers top-to-bottom by default (vertical orientation)", () => {
    const layout = computeFlowLayout(["a", "b", "c"], CHAIN);
    const byId = new Map(layout.nodes.map((n) => [n.id, n]));
    expect(byId.get("a")!.y).toBeLessThan(byId.get("b")!.y);
    expect(byId.get("b")!.y).toBeLessThan(byId.get("c")!.y);
    expect(layout.layerCount).toBe(3);
    expect(layout.width).toBeGreaterThan(0);
    expect(layout.height).toBeGreaterThan(0);
  });

  it("flows layers left-to-right when horizontal", () => {
    const layout = computeFlowLayout(["a", "b", "c"], CHAIN, { orientation: "horizontal" });
    const byId = new Map(layout.nodes.map((n) => [n.id, n]));
    expect(byId.get("a")!.x).toBeLessThan(byId.get("b")!.x);
    expect(byId.get("b")!.x).toBeLessThan(byId.get("c")!.x);
  });

  it("keeps every node inside the reported canvas", () => {
    const ids = ["a", "b", "c", "d", "e"];
    const layout = computeFlowLayout(ids, [
      { source: "a", target: "b" },
      { source: "a", target: "c" },
      { source: "b", target: "d" },
      { source: "c", target: "d" },
      { source: "d", target: "e" },
    ]);
    for (const n of layout.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThan(layout.width);
      expect(n.y).toBeLessThan(layout.height);
    }
  });

  it("orders siblings near their parents (barycenter)", () => {
    // Two parents in column 0; each has one child. Children should not cross.
    const layout = computeFlowLayout(["p1", "p2", "c1", "c2"], [
      { source: "p1", target: "c1" },
      { source: "p2", target: "c2" },
    ]);
    const byId = new Map(layout.nodes.map((n) => [n.id, n]));
    const parentOrder = byId.get("p1")!.row < byId.get("p2")!.row;
    const childOrder = byId.get("c1")!.row < byId.get("c2")!.row;
    expect(childOrder).toBe(parentOrder);
  });

  it("returns an empty layout for no nodes", () => {
    const layout = computeFlowLayout([], []);
    expect(layout.nodes).toEqual([]);
    expect(layout.width).toBe(0);
  });
});

describe("wrapTitle", () => {
  it("keeps a short title on one line", () => {
    expect(wrapTitle("Short title", 30)).toEqual(["Short title"]);
  });

  it("wraps a long title onto two lines without cutting words", () => {
    const lines = wrapTitle("Frontier AI clears a hard science autonomy benchmark", 30);
    expect(lines).toHaveLength(2);
    expect(lines[0]!.length).toBeLessThanOrEqual(30);
    expect(lines.join(" ")).toContain("Frontier AI clears");
  });

  it("ellipsizes only past two lines", () => {
    const lines = wrapTitle(
      "An extremely long market title that cannot possibly fit into two narrow lines of text at all",
      20,
    );
    expect(lines).toHaveLength(2);
    expect(lines[1]!.endsWith("…")).toBe(true);
  });
});
