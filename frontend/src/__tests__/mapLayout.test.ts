import { describe, it, expect } from "vitest";
import {
  classifyVariable,
  parseYearFromTitle,
  FAMILY_ORDER,
  FAMILY_KEYS,
  buildAdjacency,
  packYearCollisions,
  deltaToColor,
  deltaIntensity,
  computeMapLayout,
  DELTA_WARM_HEX,
  DELTA_COOL_HEX,
  DELTA_NEUTRAL_HEX,
  sourceTag,
  type GraphMarketInput,
} from "@/features/graph/mapLayout";

describe("classifyVariable", () => {
  it("parses an auto_goods by-year id with a tier", () => {
    expect(classifyVariable("ftm_auto_goods_t2_by_2035", "Task automation 50% by 2035")).toEqual({
      family: "auto_goods",
      tier: 2,
      year: 2035,
    });
  });

  it("parses an in-year id (gwp_growth)", () => {
    expect(classifyVariable("ftm_gwp_growth_t1_in_2031", "GWP growth 20% in 2031")).toEqual({
      family: "gwp_growth",
      tier: 1,
      year: 2031,
    });
  });

  it("parses an untiered id with tier null (agi)", () => {
    expect(classifyVariable("ftm_agi_by_2033", "AGI compute threshold by 2033")).toEqual({
      family: "agi",
      tier: null,
      year: 2033,
    });
  });

  it("parses gwp_growth_max distinctly from gwp_growth", () => {
    expect(classifyVariable("ftm_gwp_growth_max_t2_in_2040", "title")).toEqual({
      family: "gwp_growth_max",
      tier: 2,
      year: 2040,
    });
  });

  it("classifies x_ variables as external and parses year from the title", () => {
    expect(classifyVariable("x_0042", "Will AGI be reached before 2030? (Metaculus)")).toEqual({
      family: "external",
      tier: null,
      year: 2030,
    });
  });

  it("picks the max year when multiple years appear in an external title", () => {
    expect(classifyVariable("x_0099", "From 2028 to 2041, will this resolve?")).toEqual({
      family: "external",
      tier: null,
      year: 2041,
    });
  });

  it("classifies unknown ids as other/undated when no year is present", () => {
    expect(classifyVariable("m13", "A hand-authored original market")).toEqual({
      family: "other",
      tier: null,
      year: null,
    });
  });

  it("falls back to other/undated for a malformed ftm_ id", () => {
    expect(classifyVariable("ftm_totally_unstructured", "no year here")).toEqual({
      family: "other",
      tier: null,
      year: null,
    });
  });

  it("falls back to the title year when an ftm_ id doesn't match the by/in pattern", () => {
    expect(classifyVariable("ftm_weird_shape", "Resolves sometime in 2039")).toEqual({
      family: "other",
      tier: null,
      year: 2039,
    });
  });

  it("treats an unrecognized ftm_ family token as other, keeping the parsed year", () => {
    expect(classifyVariable("ftm_totally_new_concept_by_2030", "title")).toEqual({
      family: "other",
      tier: null,
      year: 2030,
    });
  });
});

describe("parseYearFromTitle", () => {
  it("returns null when no year matches", () => {
    expect(parseYearFromTitle("No year in here")).toBeNull();
  });

  it("ignores years outside the 2020-2069 window", () => {
    expect(parseYearFromTitle("In 1999 and 2071, but also 2033")).toBe(2033);
  });
});

describe("FAMILY_ORDER", () => {
  it("has the 15 bands in the specified fixed order with display labels", () => {
    expect(FAMILY_ORDER.map((f) => f.key)).toEqual([
      "agi",
      "rampup",
      "auto_goods",
      "full_auto",
      "rampup_rnd",
      "auto_rnd",
      "full_auto_rnd",
      "train_run",
      "gwp_compute",
      "hw_ratio",
      "sw_ratio",
      "gwp_growth",
      "gwp_growth_max",
      "external",
      "other",
    ]);
    expect(FAMILY_ORDER[0]).toMatchObject({ label: "AGI compute threshold" });
    expect(FAMILY_ORDER[FAMILY_ORDER.length - 1]).toMatchObject({ key: "other" });
    expect(FAMILY_KEYS.size).toBe(15);
  });

  it("groups families into exactly 6 categorical color groups", () => {
    const groups = new Set(FAMILY_ORDER.map((f) => f.group));
    expect(groups.size).toBe(6);
  });
});

describe("buildAdjacency", () => {
  const markets: GraphMarketInput[] = [
    { id: "m1", variableId: "ftm_agi_by_2033", title: "AGI", status: "active" },
    {
      id: "m2",
      variableId: "ftm_rampup_by_2034",
      title: "Rampup",
      status: "active",
      parents: ["ftm_agi_by_2033"],
    },
    {
      id: "m3",
      variableId: "ftm_auto_goods_t1_by_2035",
      title: "Auto",
      status: "active",
      parents: ["ftm_agi_by_2033", "ftm_rampup_by_2034"],
    },
  ];

  it("resolves parent variableIds to market ids", () => {
    const adj = buildAdjacency(markets);
    expect(adj.parentsOf.get("m2")).toEqual(["m1"]);
    expect(adj.parentsOf.get("m3")).toEqual(["m1", "m2"]);
    expect(adj.parentsOf.get("m1")).toEqual([]);
  });

  it("builds the reverse (children) map", () => {
    const adj = buildAdjacency(markets);
    expect(adj.childrenOf.get("m1")?.sort()).toEqual(["m2", "m3"]);
    expect(adj.childrenOf.get("m2")).toEqual(["m3"]);
  });

  it("ignores parent references that don't resolve to a known market", () => {
    const withDangling: GraphMarketInput[] = [
      { id: "m1", variableId: "ftm_agi_by_2033", title: "AGI", status: "active", parents: ["ftm_nonexistent"] },
    ];
    const adj = buildAdjacency(withDangling);
    expect(adj.parentsOf.get("m1")).toEqual([]);
  });
});

describe("packYearCollisions", () => {
  it("assigns distinct stack indices to items sharing a year", () => {
    const stacks = packYearCollisions([
      { id: "b", year: 2030 },
      { id: "a", year: 2030 },
      { id: "c", year: 2031 },
    ]);
    expect(stacks.get("a")).toBe(0);
    expect(stacks.get("b")).toBe(1);
    expect(stacks.get("c")).toBe(0);
  });

  it("is deterministic regardless of input order (sorted by id within a year)", () => {
    const forward = packYearCollisions([{ id: "x", year: 2030 }, { id: "y", year: 2030 }]);
    const backward = packYearCollisions([{ id: "y", year: 2030 }, { id: "x", year: 2030 }]);
    expect(forward.get("x")).toBe(backward.get("x"));
    expect(forward.get("y")).toBe(backward.get("y"));
  });
});

describe("computeMapLayout: external band collision nudging", () => {
  it("gives external markets sharing a year distinct y positions", () => {
    const markets: GraphMarketInput[] = [
      { id: "x1", variableId: "x_0001", title: "Question A, resolves 2030", status: "active" },
      { id: "x2", variableId: "x_0002", title: "Question B, resolves 2030", status: "active" },
      { id: "x3", variableId: "x_0003", title: "Question C, resolves 2030", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    const ys = layout.nodes.map((n) => n.y);
    expect(new Set(ys).size).toBe(3);
    // same x (same year column)
    const xs = new Set(layout.nodes.map((n) => n.x));
    expect(xs.size).toBe(1);
    const band = layout.bands.find((b) => b.family === "external")!;
    expect(band.rows).toBeGreaterThanOrEqual(3);
  });

  it("gives untiered ftm markets in the same family/year distinct y via collision-safe defaults", () => {
    // Two markets with no year (undated) in the same flat "other" band should
    // still not collide.
    const markets: GraphMarketInput[] = [
      { id: "o1", variableId: "m1", title: "Original one", status: "active" },
      { id: "o2", variableId: "m2", title: "Original two", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    const ys = layout.nodes.map((n) => n.y);
    expect(new Set(ys).size).toBe(2);
  });
});

describe("computeMapLayout: general shape", () => {
  it("orders bands top-to-bottom per FAMILY_ORDER and sizes height/width from data", () => {
    const markets: GraphMarketInput[] = [
      { id: "m1", variableId: "ftm_agi_by_2030", title: "AGI", status: "active" },
      { id: "m2", variableId: "ftm_other_family_by_2031", title: "Unknown family", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    const agiBand = layout.bands.find((b) => b.family === "agi")!;
    const otherBand = layout.bands.find((b) => b.family === "other")!;
    expect(agiBand.y0).toBeLessThan(otherBand.y0);
    expect(layout.height).toBeGreaterThan(0);
    expect(layout.width).toBeGreaterThan(0);
  });

  it("places t0 above t3 within a tiered band (lowest tier = top row)", () => {
    const markets: GraphMarketInput[] = [
      { id: "m0", variableId: "ftm_auto_goods_t0_by_2030", title: "t0", status: "active" },
      { id: "m3", variableId: "ftm_auto_goods_t3_by_2030", title: "t3", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    const n0 = layout.nodes.find((n) => n.id === "m0")!;
    const n3 = layout.nodes.find((n) => n.id === "m3")!;
    expect(n0.y).toBeLessThan(n3.y);
  });

  it("puts undated markets in a column to the right of the last dated year", () => {
    const markets: GraphMarketInput[] = [
      { id: "m1", variableId: "ftm_agi_by_2045", title: "latest dated", status: "active" },
      { id: "m2", variableId: "m2", title: "no year anywhere", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    const dated = layout.nodes.find((n) => n.id === "m1")!;
    const undated = layout.nodes.find((n) => n.id === "m2")!;
    expect(undated.x).toBeGreaterThan(dated.x);
  });

  it("computes edges with sameBand flag and a neighbor map from parents", () => {
    const markets: GraphMarketInput[] = [
      { id: "m1", variableId: "ftm_agi_by_2030", title: "AGI", status: "active" },
      {
        id: "m2",
        variableId: "ftm_agi_by_2031",
        title: "AGI 2",
        status: "active",
        parents: ["ftm_agi_by_2030"],
      },
      {
        id: "m3",
        variableId: "ftm_train_run_t1_by_2032",
        title: "Train run",
        status: "active",
        parents: ["ftm_agi_by_2030"],
      },
    ];
    const layout = computeMapLayout(markets);
    expect(layout.edges).toHaveLength(2);
    const sameBandEdge = layout.edges.find((e) => e.target === "m2")!;
    const crossBandEdge = layout.edges.find((e) => e.target === "m3")!;
    expect(sameBandEdge.sameBand).toBe(true);
    expect(crossBandEdge.sameBand).toBe(false);
    expect(layout.neighborsOf.get("m1")).toEqual(new Set(["m2", "m3"]));
    expect(layout.neighborsOf.get("m2")).toEqual(new Set(["m1"]));
  });
});

describe("deltaIntensity / deltaToColor", () => {
  it("is zero inside the neutral window", () => {
    expect(deltaIntensity(0)).toBe(0);
    expect(deltaIntensity(0.004)).toBe(0);
    expect(deltaIntensity(-0.004)).toBe(0);
    expect(deltaToColor(0.002)).toBe(DELTA_NEUTRAL_HEX);
  });

  it("is monotonically increasing in |delta| outside the neutral window", () => {
    const deltas = [0.006, 0.02, 0.05, 0.1, 0.2, 0.3];
    const intensities = deltas.map(deltaIntensity);
    for (let i = 1; i < intensities.length; i++) {
      expect(intensities[i]).toBeGreaterThan(intensities[i - 1]!);
    }
    // caps at 1 once |delta| reaches DELTA_CAP (0.25)
    expect(deltaIntensity(0.3)).toBe(1);
  });

  it("uses the warm pole for negative delta and the cool pole for positive delta at full intensity", () => {
    expect(deltaToColor(-0.5)).toBe(DELTA_WARM_HEX);
    expect(deltaToColor(0.5)).toBe(DELTA_COOL_HEX);
  });

  it("negative and positive deltas of the same magnitude produce different colors", () => {
    expect(deltaToColor(0.1)).not.toBe(deltaToColor(-0.1));
  });
});

describe("sourceTag", () => {
  it("prefers the anchor source when present", () => {
    expect(sourceTag({ anchor: { source: "metaculus" } })).toBe("Metaculus");
    expect(sourceTag({ anchor: { source: "manifold" } })).toBe("Manifold");
  });

  it("falls back to FTM when ftmImplied is present without an anchor", () => {
    expect(sourceTag({ ftmImplied: 0.4 })).toBe("FTM");
  });

  it("falls back to market when neither is present", () => {
    expect(sourceTag({})).toBe("market");
  });
});
