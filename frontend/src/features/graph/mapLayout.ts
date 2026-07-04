/**
 * Pure layout + classification logic for the full-network landing map
 * (see NetworkMap.tsx). Everything here is plain data in, plain data out —
 * no DOM, no React, no fetching — so it is unit-testable on its own and the
 * component just renders whatever this module computes.
 *
 * Structured timeline map, NOT force-directed:
 *   X axis = year the market resolves (parsed from the variableId or, for
 *   markets without one, from the title). Y axis = fixed horizontal "family"
 *   bands (one row of sub-bands per FTM concept, plus external + other).
 */

import { searchMatchIds as egoSearchMatchIds } from "./egoGraph";

// ---------------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------------

export interface Classification {
  family: string;
  tier: number | null;
  year: number | null;
}

/** Matches years 2020-2069 anywhere in a title; we only ever expect 2020s-2060s. */
const YEAR_IN_TITLE_RE = /20[2-6]\d/g;

/** Trailing `_by_YYYY` / `_in_YYYY`, with an optional `_t<k>` tier just before it. */
const FTM_VAR_RE = /^ftm_(.+?)(?:_t(\d))?_(?:by|in)_(\d{4})$/;

export const KNOWN_FTM_FAMILIES = new Set([
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
]);

/** Latest (max) 4-digit year found in a title, or null when none is present. */
export function parseYearFromTitle(title: string): number | null {
  const matches = title.match(YEAR_IN_TITLE_RE);
  if (!matches || matches.length === 0) return null;
  return Math.max(...matches.map(Number));
}

/**
 * Classify a market by its engine variableId (falling back to its title for
 * the year, and for family/tier when the id doesn't parse):
 *  - `x_*` ids are external imports -> family "external", year from title.
 *  - `ftm_<family>[_t<tier>]_by|in_<year>` ids parse directly.
 *  - anything else (the 16 hand-authored originals, or a malformed id) ->
 *    family "other", year from title if present, else undated (null).
 */
export function classifyVariable(
  variableId: string | undefined | null,
  title: string,
): Classification {
  const varId = variableId ?? "";

  if (varId.startsWith("x_")) {
    return { family: "external", tier: null, year: parseYearFromTitle(title) };
  }

  if (varId.startsWith("ftm_")) {
    const m = FTM_VAR_RE.exec(varId);
    if (m) {
      const family = m[1]!;
      const tier = m[2] !== undefined ? Number(m[2]) : null;
      const year = Number(m[3]);
      return { family: KNOWN_FTM_FAMILIES.has(family) ? family : "other", tier, year };
    }
  }

  return { family: "other", tier: null, year: parseYearFromTitle(title) };
}

// ---------------------------------------------------------------------------
// Bands (Y axis)
// ---------------------------------------------------------------------------

export type GroupKey =
  | "agi_rampup"
  | "automation"
  | "compute"
  | "efficiency"
  | "economy"
  | "external_other";

export interface FamilyMeta {
  key: string;
  label: string;
  group: GroupKey;
}

/** Fixed band order top -> bottom, per the product spec. */
export const FAMILY_ORDER: FamilyMeta[] = [
  { key: "agi", label: "AGI compute threshold", group: "agi_rampup" },
  { key: "rampup", label: "Economic ramp-up (20%)", group: "agi_rampup" },
  { key: "auto_goods", label: "Task automation — economy", group: "automation" },
  { key: "full_auto", label: "Full automation — economy", group: "automation" },
  { key: "rampup_rnd", label: "R&D automation (20%)", group: "agi_rampup" },
  { key: "auto_rnd", label: "Task automation — R&D", group: "automation" },
  { key: "full_auto_rnd", label: "Full automation — R&D", group: "automation" },
  { key: "train_run", label: "Largest training run", group: "compute" },
  { key: "gwp_compute", label: "Compute investment share", group: "compute" },
  { key: "hw_ratio", label: "Hardware price-performance", group: "efficiency" },
  { key: "sw_ratio", label: "Software efficiency", group: "efficiency" },
  { key: "gwp_growth", label: "GWP growth (in-year)", group: "economy" },
  { key: "gwp_growth_max", label: "GWP growth (ever exceeded)", group: "economy" },
  { key: "external", label: "External forecasts (Metaculus/Manifold)", group: "external_other" },
  { key: "other", label: "Other", group: "external_other" },
];

export const FAMILY_KEYS = new Set(FAMILY_ORDER.map((f) => f.key));

// ---------------------------------------------------------------------------
// Categorical group palette
//
// Validated on the dark app surface (#0f1117, var(--color-bg)) with the
// dataviz skill's validator:
//
//   node validate_palette.js \
//     "#0083c4,#c83046,#605edc,#00925e,#6f7d00,#b73790" \
//     --mode dark --surface "#0f1117" --pairs all
//
//   Palette (dark, surface #0f1117, categorical): 6 slots
//     [PASS] Lightness band         all 6 inside L 0.48–0.67
//     [PASS] Chroma floor           all 6 >= 0.1
//     [PASS] CVD separation         worst all-pairs #00925e↔#c83046 ΔE 16.0
//            (deutan) · tritan 12.2 · normal 44.9
//     [PASS] Contrast vs surface    all 6 >= 3:1
//     -> ALL CHECKS PASS
//
// --pairs all (not just adjacent) was used deliberately: every node is
// visible simultaneously on one map (like a scatter/bubble chart), so any
// two group colors can end up next to each other, not just neighbors in a
// legend list. Colors are also double-encoded by fixed band position + band
// label, so hue is never the sole identity carrier.
// ---------------------------------------------------------------------------

export const GROUP_COLORS: Record<GroupKey, string> = {
  agi_rampup: "#0083c4", // blue
  automation: "#c83046", // red
  compute: "#605edc", // indigo
  efficiency: "#00925e", // teal-green
  economy: "#6f7d00", // olive / yellow-green
  external_other: "#b73790", // magenta
};

export function colorForGroup(group: GroupKey): string {
  return GROUP_COLORS[group];
}

// ---------------------------------------------------------------------------
// Assumption-delta diverging encoding
//
// Poles validated the same way (2-slot categorical check covers hue/lightness
// /chroma/contrast identically; a diverging pair is just N=2 here):
//
//   node validate_palette.js "#d75928,#0095d7" --mode dark --surface "#0f1117" --pairs all
//
//   Palette (dark, surface #0f1117, categorical): 2 slots
//     [PASS] Lightness band, Chroma floor, Contrast vs surface
//     [PASS] CVD separation  worst all-pairs ΔE 83.8 (protan) · tritan 110.0 · normal 109.5
//     -> ALL CHECKS PASS
// ---------------------------------------------------------------------------

/** Warm pole: assumptions pushed this market's Yes price DOWN. */
export const DELTA_WARM_HEX = "#d75928";
/** Cool pole: assumptions pushed this market's Yes price UP. */
export const DELTA_COOL_HEX = "#0095d7";
/** Near-zero shift; also the resting/no-assumption node color in delta mode. */
export const DELTA_NEUTRAL_HEX = "#6b7280";

/** |delta probability| below this reads as "no meaningful change". */
export const DELTA_NEUTRAL_WINDOW = 0.005;
/** Delta probability magnitude at which color intensity saturates (25 pts). */
export const DELTA_CAP = 0.25;

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function rgbToHex(rgb: [number, number, number]): string {
  const c = (v: number) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0");
  return `#${c(rgb[0])}${c(rgb[1])}${c(rgb[2])}`;
}

function lerpHex(a: string, b: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  return rgbToHex([ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t]);
}

/**
 * Monotonic 0-1 intensity for a delta probability: 0 inside the neutral
 * window, ramping linearly to 1 at |delta| == DELTA_CAP (and beyond).
 */
export function deltaIntensity(delta: number): number {
  const abs = Math.abs(delta);
  if (abs < DELTA_NEUTRAL_WINDOW) return 0;
  const span = DELTA_CAP - DELTA_NEUTRAL_WINDOW;
  return Math.min(1, (abs - DELTA_NEUTRAL_WINDOW) / span);
}

/**
 * delta = conditional.yes - base.yes. Negative -> warm, positive -> cool,
 * |delta| < DELTA_NEUTRAL_WINDOW -> neutral gray. Intensity (saturation
 * toward the pole) scales with |delta|, capped at DELTA_CAP.
 */
export function deltaToColor(delta: number): string {
  const t = deltaIntensity(delta);
  if (t === 0) return DELTA_NEUTRAL_HEX;
  const pole = delta > 0 ? DELTA_COOL_HEX : DELTA_WARM_HEX;
  return lerpHex(DELTA_NEUTRAL_HEX, pole, t);
}

// ---------------------------------------------------------------------------
// Source tag
// ---------------------------------------------------------------------------

export type SourceTag = "FTM" | "Metaculus" | "Manifold" | "market";

export function sourceTag(market: {
  anchor?: { source: "metaculus" | "manifold" };
  ftmImplied?: number | null;
}): SourceTag {
  if (market.anchor?.source === "metaculus") return "Metaculus";
  if (market.anchor?.source === "manifold") return "Manifold";
  if (market.ftmImplied !== undefined && market.ftmImplied !== null) return "FTM";
  return "market";
}

// ---------------------------------------------------------------------------
// Adjacency
// ---------------------------------------------------------------------------

export interface GraphMarketInput {
  id: string;
  variableId?: string;
  title: string;
  status: string;
  parents?: string[];
}

export interface Adjacency {
  parentsOf: Map<string, string[]>;
  childrenOf: Map<string, string[]>;
}

/** parents on a market are PARENT VARIABLE IDS; resolve them to market ids. */
export function buildAdjacency(markets: GraphMarketInput[]): Adjacency {
  const idByVariable = new Map<string, string>();
  for (const m of markets) if (m.variableId) idByVariable.set(m.variableId, m.id);

  const parentsOf = new Map<string, string[]>();
  const childrenOf = new Map<string, string[]>();
  for (const m of markets) {
    parentsOf.set(m.id, []);
    childrenOf.set(m.id, []);
  }
  for (const m of markets) {
    for (const parentVar of m.parents ?? []) {
      const parentId = idByVariable.get(parentVar);
      if (!parentId || parentId === m.id || !parentsOf.has(parentId)) continue;
      parentsOf.get(m.id)!.push(parentId);
      childrenOf.get(parentId)!.push(m.id);
    }
  }
  return { parentsOf, childrenOf };
}

// ---------------------------------------------------------------------------
// Collision nudging (used for the external band, and defensively anywhere
// else multiple nodes land on the exact same year within one row)
// ---------------------------------------------------------------------------

export interface YearSlotItem {
  id: string;
  year: number;
}

/**
 * Deterministic stack index (0-based) per item, grouped by `year`; items
 * sharing a year are ordered by id so the assignment never depends on input
 * order. Used to nudge same-year nodes into mini-rows instead of drawing
 * them on top of each other.
 */
export function packYearCollisions(items: YearSlotItem[]): Map<string, number> {
  const byYear = new Map<number, string[]>();
  for (const it of items) {
    const arr = byYear.get(it.year) ?? [];
    arr.push(it.id);
    byYear.set(it.year, arr);
  }
  const result = new Map<string, number>();
  for (const ids of byYear.values()) {
    const sorted = [...ids].sort();
    sorted.forEach((id, i) => result.set(id, i));
  }
  return result;
}

// ---------------------------------------------------------------------------
// Full layout
// ---------------------------------------------------------------------------

export const YEAR_MIN = 2027;
export const YEAR_MAX = 2045;

/** Flat bands (external/other) wrap their per-column stacks past this depth. */
export const FLAT_MAX_ROWS = 14;
/** Horizontal pitch between wrapped sub-columns inside one year slot. */
export const FLAT_SUBCOL_PITCH = 7;

export interface PositionedMapNode {
  id: string;
  x: number;
  y: number;
  family: string;
  group: GroupKey;
  tier: number | null;
  year: number | null;
  undated: boolean;
}

export interface MapBand {
  family: string;
  label: string;
  group: GroupKey;
  y0: number;
  y1: number;
  rows: number;
}

export interface MapEdge {
  source: string;
  target: string;
  sameBand: boolean;
}

export interface MapLayout {
  nodes: PositionedMapNode[];
  bands: MapBand[];
  edges: MapEdge[];
  neighborsOf: Map<string, Set<string>>;
  width: number;
  height: number;
  yearMin: number;
  yearMax: number;
  yearToX: (year: number | null) => number;
  leftMargin: number;
  topMargin: number;
}

export interface MapLayoutOptions {
  leftMargin?: number;
  topMargin?: number;
  yearPitch?: number;
  rowHeight?: number;
  bandGap?: number;
  rightPadding?: number;
  bottomPadding?: number;
}

const DEFAULT_LAYOUT_OPTIONS: Required<MapLayoutOptions> = {
  leftMargin: 190,
  topMargin: 24,
  yearPitch: 40,
  rowHeight: 18,
  bandGap: 6,
  rightPadding: 32,
  bottomPadding: 12,
};

/** A quadratic-Bézier path string; used for a subtle within-band curve and a
 * more pronounced curve for cross-band (implication vs. cross-cutting) edges. */
export function edgeBezierPath(x1: number, y1: number, x2: number, y2: number, sameBand: boolean): string {
  const mx = (x1 + x2) / 2;
  const bow = sameBand ? Math.min(14, Math.abs(y2 - y1) / 2 + 6) : Math.min(46, Math.abs(y2 - y1) / 2 + 18);
  const my = (y1 + y2) / 2 - bow;
  return `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`;
}

export function computeMapLayout(
  markets: GraphMarketInput[],
  options: MapLayoutOptions = {},
): MapLayout {
  const opts = { ...DEFAULT_LAYOUT_OPTIONS, ...options };
  // Column model: 0 = "≤2026", 1..19 = 2027..2045, 20 = "2046+", 21 = undated.
  const preColumn = 0;
  const postColumn = YEAR_MAX - YEAR_MIN + 2;
  const undatedColumn = postColumn + 1;

  const columnOf = (year: number | null): number => {
    if (year === null) return undatedColumn;
    if (year < YEAR_MIN) return preColumn;
    if (year > YEAR_MAX) return postColumn;
    return year - YEAR_MIN + 1;
  };

  const yearToX = (year: number | null): number => {
    return opts.leftMargin + columnOf(year) * opts.yearPitch;
  };

  const classified = markets.map((m) => ({ market: m, cls: classifyVariable(m.variableId, m.title) }));

  const byFamily = new Map<string, typeof classified>();
  for (const entry of classified) {
    const key = FAMILY_KEYS.has(entry.cls.family) ? entry.cls.family : "other";
    if (!byFamily.has(key)) byFamily.set(key, []);
    byFamily.get(key)!.push(entry);
  }

  const bands: MapBand[] = [];
  const nodes: PositionedMapNode[] = [];
  let cursorY = opts.topMargin;

  for (const meta of FAMILY_ORDER) {
    const entries = byFamily.get(meta.key) ?? [];
    const isFlatBand = meta.key === "external" || meta.key === "other";

    let rowOf: (cls: Classification) => number;
    let rows: number;

    if (isFlatBand) {
      // Dense packing: nodes sharing a column stack downward, wrapping into
      // centered sub-columns past FLAT_MAX_ROWS so no column becomes a
      // page-long spike (the undated bucket alone holds ~100 externals).
      const byColumn = new Map<number, typeof entries>();
      for (const e of entries) {
        const col = columnOf(e.cls.year);
        if (!byColumn.has(col)) byColumn.set(col, []);
        byColumn.get(col)!.push(e);
      }
      let maxRows = 1;
      const y0 = cursorY;
      for (const [col, colEntries] of byColumn) {
        const sorted = [...colEntries].sort((a, b) => (a.market.id < b.market.id ? -1 : 1));
        const subCols = Math.ceil(sorted.length / FLAT_MAX_ROWS);
        maxRows = Math.max(maxRows, Math.min(sorted.length, FLAT_MAX_ROWS));
        sorted.forEach((e, i) => {
          const subCol = Math.floor(i / FLAT_MAX_ROWS);
          const row = i % FLAT_MAX_ROWS;
          const xOffset = (subCol - (subCols - 1) / 2) * FLAT_SUBCOL_PITCH;
          nodes.push({
            id: e.market.id,
            x: opts.leftMargin + col * opts.yearPitch + xOffset,
            y: y0 + row * opts.rowHeight + opts.rowHeight / 2,
            family: meta.key,
            group: meta.group,
            tier: e.cls.tier,
            year: e.cls.year,
            undated: e.cls.year === null,
          });
        });
      }
      rows = maxRows;
      rowOf = (_cls) => 0; // node positions were assigned per-item above
      const y1 = y0 + rows * opts.rowHeight;
      bands.push({ family: meta.key, label: meta.label, group: meta.group, y0, y1, rows });
      cursorY = y1 + opts.bandGap;
      continue;
    }

    // Tiered band: one sub-row per distinct tier seen in the data (t0 top),
    // defaulting untiered markets to row 0.
    const tiers = Array.from(new Set(entries.map((e) => e.cls.tier ?? 0))).sort((a, b) => a - b);
    const rowIndexOfTier = new Map(tiers.map((t, i) => [t, i]));
    rows = Math.max(1, tiers.length);
    rowOf = (cls) => rowIndexOfTier.get(cls.tier ?? 0) ?? 0;

    const y0 = cursorY;
    for (const e of entries) {
      const row = rowOf(e.cls);
      nodes.push({
        id: e.market.id,
        x: yearToX(e.cls.year),
        y: y0 + row * opts.rowHeight + opts.rowHeight / 2,
        family: meta.key,
        group: meta.group,
        tier: e.cls.tier,
        year: e.cls.year,
        undated: e.cls.year === null,
      });
    }
    const y1 = y0 + rows * opts.rowHeight;
    bands.push({ family: meta.key, label: meta.label, group: meta.group, y0, y1, rows });
    cursorY = y1 + opts.bandGap;
  }

  const familyById = new Map(nodes.map((n) => [n.id, n.family]));
  const adjacency = buildAdjacency(markets);
  const idSet = new Set(markets.map((m) => m.id));
  const edges: MapEdge[] = [];
  for (const [childId, parentIds] of adjacency.parentsOf) {
    if (!idSet.has(childId)) continue;
    for (const parentId of parentIds) {
      edges.push({
        source: parentId,
        target: childId,
        sameBand: familyById.get(parentId) === familyById.get(childId),
      });
    }
  }

  const neighborsOf = new Map<string, Set<string>>();
  for (const n of nodes) neighborsOf.set(n.id, new Set());
  for (const e of edges) {
    neighborsOf.get(e.source)?.add(e.target);
    neighborsOf.get(e.target)?.add(e.source);
  }

  const height = (bands.length > 0 ? cursorY - opts.bandGap : opts.topMargin) + opts.bottomPadding;
  const width = opts.leftMargin + (undatedColumn + 1) * opts.yearPitch + opts.rightPadding;

  return {
    nodes,
    bands,
    edges,
    neighborsOf,
    width,
    height,
    yearMin: YEAR_MIN,
    yearMax: YEAR_MAX,
    yearToX,
    leftMargin: opts.leftMargin,
    topMargin: opts.topMargin,
  };
}

/** Re-exported so NetworkMap.tsx has one import surface for map utilities. */
export const searchMatchIds = egoSearchMatchIds;
