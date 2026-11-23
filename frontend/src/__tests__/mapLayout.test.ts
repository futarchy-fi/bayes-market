import { describe, it, expect } from "vitest";
import {
  classifyVariable,
  parseYearFromTitle,
  FAMILY_ORDER,
  FAMILY_KEYS,
  GROUP_COLORS,
  GROUP_LABELS,
  YEAR_MIN,
  YEAR_MAX,
  buildAdjacency,
  buildCategoryPills,
  matchesMarketCategory,
  packYearCollisions,
  deltaToColor,
  deltaIntensity,
  computeMapLayout,
  DELTA_WARM_HEX,
  DELTA_COOL_HEX,
  DELTA_NEUTRAL_HEX,
  sourceTag,
  probabilityFillOpacity,
  probabilityRadius,
  selectSnapshotKpis,
  selectWhatIfScenarios,
  isContextContradictedError,
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

  it("classifies dw_*, pol_*, and fut_* variables into dedicated thematic families", () => {
    expect(classifyVariable("dw_paul_christiano_agi_by_2030", "Dwarkesh: Paul Christiano on AGI")).toEqual({
      family: "dwarkesh",
      tier: null,
      year: 2030,
    });
    expect(classifyVariable("pol_us_compute_cap", "US federal compute cap before 2029?")).toEqual({
      family: "policy",
      tier: null,
      year: 2029,
    });
    expect(classifyVariable("fut_existential_risk_2040", "Major AI catastrophe?")).toEqual({
      family: "futurist",
      tier: null,
      year: 2040,
    });
    expect(classifyVariable("pol_open_weights_ban", "Will Congress restrict open weights?")).toEqual({
      family: "policy",
      tier: null,
      year: null,
    });
  });

  it("classifies x_ variables as external and parses year from the title", () => {
    expect(classifyVariable("x_0042", "Will AGI be reached before 2030? (Manifold)")).toEqual({
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

describe("FAMILY_ORDER & GROUP_COLORS", () => {
  it("has the 19 bands in fixed order including Dwarkesh, Policy, and Futurist", () => {
    expect(FAMILY_ORDER.map((f) => f.key)).toEqual([
      "agi",
      "sub_agi",
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
      "dwarkesh",
      "policy",
      "futurist",
      "external",
      "other",
    ]);
    expect(FAMILY_ORDER[0]).toMatchObject({ label: "AGI compute threshold" });
    expect(FAMILY_ORDER[1]).toMatchObject({ key: "sub_agi", label: "Weakly general AI (Sub-AGI)", group: "agi_rampup" });
    expect(FAMILY_ORDER.find((f) => f.key === "dwarkesh")).toEqual({ key: "dwarkesh", label: "Dwarkesh Podcast", group: "dwarkesh" });
    expect(FAMILY_ORDER.find((f) => f.key === "policy")).toEqual({ key: "policy", label: "AI Policy & Regulation", group: "policy" });
    expect(FAMILY_ORDER.find((f) => f.key === "futurist")).toEqual({ key: "futurist", label: "Futurist & Doomer", group: "futurist" });
    expect(FAMILY_ORDER.find((f) => f.key === "external")).toEqual({ key: "external", label: "External forecasts (Manifold)", group: "external_other" });
    expect(FAMILY_ORDER[FAMILY_ORDER.length - 1]).toMatchObject({ key: "other" });
    expect(FAMILY_KEYS.size).toBe(19);
  });

  it("groups families into 9 categorical color groups with distinct thematic colors", () => {
    const groups = new Set(FAMILY_ORDER.map((f) => f.group));
    expect(groups.size).toBe(9);
    expect(GROUP_COLORS.dwarkesh).toBe("#f59e0b");
    expect(GROUP_COLORS.policy).toBe("#14b8a6");
    expect(GROUP_COLORS.futurist).toBe("#a855f7");
    expect(GROUP_COLORS.external_other).toBe("#ec4899");
    expect(GROUP_LABELS.dwarkesh).toBe("Dwarkesh");
    expect(GROUP_LABELS.policy).toBe("Policy");
    expect(GROUP_LABELS.futurist).toBe("Futurist");
    expect(GROUP_LABELS.external_other).toBe("External");
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

describe("computeMapLayout: short timelines 2027-2035 + 2036+ and flat bands", () => {
  it("uses short-timelines horizon 2027..2035 and maps 2036+ years to one post column", () => {
    expect(YEAR_MIN).toBe(2027);
    expect(YEAR_MAX).toBe(2035);
    const markets: GraphMarketInput[] = [
      { id: "m35", variableId: "ftm_agi_by_2035", title: "AGI 2035", status: "active" },
      { id: "f36", variableId: "fut_civilization_by_2036", title: "Civilization 2036", status: "active" },
      { id: "f50", variableId: "fut_dyson_by_2050", title: "Dyson 2050", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    expect(layout.yearMin).toBe(2027);
    expect(layout.yearMax).toBe(2035);
    expect(layout.hasUndated).toBe(false);

    const n35 = layout.nodes.find((n) => n.id === "m35")!;
    const n36 = layout.nodes.find((n) => n.id === "f36")!;
    const n50 = layout.nodes.find((n) => n.id === "f50")!;
    expect(n36.x).toBeGreaterThan(n35.x);
    expect(n36.x).toBe(n50.x);
    // Two futurist markets in the 2036+ bucket must stack cleanly without colliding.
    expect(n36.y).not.toBe(n50.y);
  });

  it("omits undated column width when all markets have dates, and adds it when undated exist", () => {
    const datedOnly = computeMapLayout([
      { id: "m1", variableId: "ftm_agi_by_2035", title: "AGI 2035", status: "active" },
    ]);
    const withUndated = computeMapLayout([
      { id: "m1", variableId: "ftm_agi_by_2035", title: "AGI 2035", status: "active" },
      { id: "m2", variableId: "pol_liability", title: "Congress AI liability law", status: "active" },
    ]);
    expect(datedOnly.hasUndated).toBe(false);
    expect(withUndated.hasUndated).toBe(true);
    expect(withUndated.width).toBeGreaterThan(datedOnly.width);
  });

  it("gives dwarkesh, policy, futurist, and external markets sharing a year distinct y positions", () => {
    const markets: GraphMarketInput[] = [
      { id: "d1", variableId: "dw_ep1_by_2030", title: "Dwarkesh A", status: "active" },
      { id: "d2", variableId: "dw_ep2_by_2030", title: "Dwarkesh B", status: "active" },
      { id: "x1", variableId: "x_0001", title: "Question A, resolves 2030", status: "active" },
      { id: "x2", variableId: "x_0002", title: "Question B, resolves 2030", status: "active" },
      { id: "x3", variableId: "x_0003", title: "Question C, resolves 2030", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    const dwNodes = layout.nodes.filter((n) => n.family === "dwarkesh");
    expect(new Set(dwNodes.map((n) => n.y)).size).toBe(2);
    expect(new Set(dwNodes.map((n) => n.x)).size).toBe(1);

    const extNodes = layout.nodes.filter((n) => n.family === "external");
    expect(new Set(extNodes.map((n) => n.y)).size).toBe(3);
    expect(new Set(extNodes.map((n) => n.x)).size).toBe(1);
    const extBand = layout.bands.find((b) => b.family === "external")!;
    expect(extBand.rows).toBeGreaterThanOrEqual(3);
  });

  it("gives untiered markets in the same flat 'other' band distinct y positions", () => {
    const markets: GraphMarketInput[] = [
      { id: "o1", variableId: "m1", title: "Original one", status: "active" },
      { id: "o2", variableId: "m2", title: "Original two", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    expect(new Set(layout.nodes.map((n) => n.y)).size).toBe(2);
  });
});

describe("computeMapLayout: general shape", () => {
  it("orders bands top-to-bottom per FAMILY_ORDER and sizes height/width from data", () => {
    const markets: GraphMarketInput[] = [
      { id: "m1", variableId: "ftm_agi_by_2030", title: "AGI", status: "active" },
      { id: "d1", variableId: "dw_ep_by_2030", title: "Dwarkesh", status: "active" },
      { id: "p1", variableId: "pol_act_by_2031", title: "Policy", status: "active" },
      { id: "f1", variableId: "fut_risk_by_2035", title: "Futurist", status: "active" },
      { id: "m2", variableId: "ftm_other_family_by_2031", title: "Unknown family", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    expect(layout.bands.map((b) => b.family)).toEqual(["agi", "dwarkesh", "policy", "futurist", "other"]);
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

  it("puts undated markets in a column to the right of the 2036+ column", () => {
    const markets: GraphMarketInput[] = [
      { id: "m1", variableId: "ftm_agi_by_2045", title: "post horizon", status: "active" },
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
  it("labels thematic variableId prefixes cleanly", () => {
    expect(sourceTag({ variableId: "dw_paul_agi_by_2030" })).toBe("Dwarkesh");
    expect(sourceTag({ variableId: "pol_compute_cap_2029" })).toBe("Policy");
    expect(sourceTag({ variableId: "fut_xrisk_2040" })).toBe("Futurist");
    expect(sourceTag({ variableId: "x_0012" })).toBe("Manifold");
    expect(sourceTag({ variableId: "ftm_agi_by_2032" })).toBe("FTM");
  });

  it("prefers the anchor source when present on non-thematic variables", () => {
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

describe("category filter pills", () => {
  it("only returns tabs with > 0 markets prefixed with All", () => {
    const markets = [
      { variableId: "ftm_agi_by_2030" },
      { variableId: "dw_scaling_by_2029" },
      { variableId: "dw_agents_by_2030" },
      { variableId: "fut_extinction_by_2040" },
    ];
    expect(buildCategoryPills(markets).map((p) => [p.key, p.label, p.count])).toEqual([
      ["all", "All", 4],
      ["ftm", "Core FTM", 1],
      ["dwarkesh", "Dwarkesh", 2],
      ["futurist", "Futurist", 1],
    ]);
    expect(matchesMarketCategory({ variableId: "dw_scaling_by_2029" }, "dwarkesh")).toBe(true);
    expect(matchesMarketCategory({ variableId: "dw_scaling_by_2029" }, "policy")).toBe(false);
    expect(matchesMarketCategory({ variableId: "misc_1" }, "all")).toBe(true);
  });

  it("returns empty array when no markets match a known category", () => {
    expect(buildCategoryPills([{ variableId: "eth" }, { variableId: "btc" }])).toEqual([]);
  });
});

describe("sub_agi, empty swimlane hiding, tier labels, KPIs, and probability encoding", () => {
  it("classifies ftm_sub_agi_by_YYYY into the sub_agi family", () => {
    expect(classifyVariable("ftm_sub_agi_by_2030", "Weakly general AI by 2030")).toEqual({
      family: "sub_agi",
      tier: null,
      year: 2030,
    });
  });

  it("hides empty swimlanes automatically", () => {
    const markets: GraphMarketInput[] = [
      { id: "m1", variableId: "ftm_agi_by_2035", title: "AGI 2035", status: "active" },
      { id: "m2", variableId: "ftm_sub_agi_by_2030", title: "Sub-AGI 2030", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    expect(layout.bands.map((b) => b.family)).toEqual(["agi", "sub_agi"]);
  });

  it("populates sub-row threshold labels on multi-tier bands", () => {
    const markets: GraphMarketInput[] = [
      { id: "a0", variableId: "ftm_auto_goods_t0_by_2030", title: "5%", status: "active" },
      { id: "a3", variableId: "ftm_auto_goods_t3_by_2035", title: "90%", status: "active" },
      { id: "tr1", variableId: "ftm_train_run_t1_by_2032", title: "1e29", status: "active" },
    ];
    const layout = computeMapLayout(markets);
    const autoBand = layout.bands.find((b) => b.family === "auto_goods")!;
    expect(autoBand.subRows.map((r) => r.label)).toEqual(["5%", "90%"]);
    const trainBand = layout.bands.find((b) => b.family === "train_run")!;
    expect(trainBand.subRows.map((r) => r.label)).toEqual(["1e29"]);
  });

  it("scales resting fillOpacity and radius monotonically with probability", () => {
    expect(probabilityFillOpacity(0.05)).toBeLessThan(probabilityFillOpacity(0.5));
    expect(probabilityFillOpacity(0.5)).toBeLessThan(probabilityFillOpacity(0.95));
    expect(probabilityRadius(0.05, 3.5)).toBeLessThan(probabilityRadius(0.95, 3.5));
  });

  it("selects short-timelines snapshot KPIs and what-if scenarios gracefully by variableId", () => {
    const markets = [
      { id: "s1", variableId: "ftm_sub_agi_by_2030", title: "Weakly General AI by 2030", status: "active" as const, marginals: { yes: 0.42, no: 0.58 } },
      { id: "a0", variableId: "ftm_agi_by_2030", title: "AGI by 2030", status: "active" as const, marginals: { yes: 0.08, no: 0.92 } },
      { id: "a1", variableId: "ftm_agi_by_2032", title: "AGI by 2032", status: "active" as const, marginals: { yes: 0.16, no: 0.84 } },
      { id: "a2", variableId: "ftm_agi_by_2035", title: "AGI by 2035", status: "active" as const, marginals: { yes: 0.34, no: 0.66 } },
      { id: "r1", variableId: "ftm_auto_rnd_t1_by_2030", title: "20% R&D auto by 2030", status: "active" as const, marginals: { yes: 0.25, no: 0.75 } },
      { id: "r2", variableId: "ftm_auto_rnd_t2_by_2032", title: "50% R&D auto by 2032", status: "active" as const, marginals: { yes: 0.19, no: 0.81 } },
      { id: "g1", variableId: "ftm_gwp_growth_max_t1_by_2035", title: "10%+ GWP growth by 2035", status: "active" as const, marginals: { yes: 0.22, no: 0.78 } },
      { id: "tr", variableId: "ftm_train_run_t1_by_2032", title: "1e29 FLOP by 2032", status: "active" as const, marginals: { yes: 0.61, no: 0.39 } },
    ];
    expect(selectSnapshotKpis(markets).map((k) => k.label)).toEqual([
      "Weakly General AI by 2030",
      "Strict AGI by 2032",
      "Strict AGI by 2035",
      "50% R&D Auto by 2032",
      "10%+ GWP Growth by 2035",
    ]);
    expect(selectWhatIfScenarios(markets).map((s) => [s.label, s.variableId])).toEqual([
      ["Assume AGI by 2030", "ftm_agi_by_2030"],
      ["Assume 20% R&D auto by 2030", "ftm_auto_rnd_t1_by_2030"],
      ["Assume 1e29 FLOP by 2032", "ftm_train_run_t1_by_2032"],
    ]);
  });

  it("detects 409 context_contradicted errors reliably", () => {
    expect(isContextContradictedError({ status: 409, code: "context_contradicted" })).toBe(true);
    expect(isContextContradictedError({ status: 500, code: "internal_error" })).toBe(false);
    expect(isContextContradictedError(null)).toBe(false);
  });
});
