/**
 * Pure graph utilities for scaling the belief-flow view: ego subgraphs
 * (focus mode), title search, and top-mover ranking. No DOM, no React —
 * everything here is testable with plain data.
 */

import type { FlowEdge } from "./flowLayout";

/**
 * The ego set of `centerId`: the center plus its ancestors up to `hops`
 * levels and its descendants up to `hops` levels (directional walks; a
 * parent's other children are NOT included). Self-loops are ignored.
 */
export function computeEgoSet(centerId: string, edges: FlowEdge[], hops = 2): Set<string> {
  const parents = new Map<string, string[]>();
  const children = new Map<string, string[]>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    if (!children.has(e.source)) children.set(e.source, []);
    children.get(e.source)!.push(e.target);
    if (!parents.has(e.target)) parents.set(e.target, []);
    parents.get(e.target)!.push(e.source);
  }

  const result = new Set<string>([centerId]);
  const walk = (adjacency: Map<string, string[]>) => {
    let frontier = [centerId];
    const seen = new Set<string>([centerId]);
    for (let hop = 0; hop < hops && frontier.length > 0; hop++) {
      const next: string[] = [];
      for (const id of frontier) {
        for (const neighbor of adjacency.get(id) ?? []) {
          if (seen.has(neighbor)) continue;
          seen.add(neighbor);
          result.add(neighbor);
          next.push(neighbor);
        }
      }
      frontier = next;
    }
  };
  walk(parents);
  walk(children);
  return result;
}

/** Edges of the induced subgraph: both endpoints must be inside `ids`. */
export function induceEdges(ids: ReadonlySet<string>, edges: FlowEdge[]): FlowEdge[] {
  return edges.filter((e) => ids.has(e.source) && ids.has(e.target));
}

/**
 * Case-insensitive substring search over node titles. Returns null when the
 * query is empty/blank (meaning: no active search, nothing should fade),
 * otherwise the set of matching node ids (possibly empty).
 */
export function searchMatchIds(
  query: string,
  nodes: Array<{ id: string; title: string }>,
): Set<string> | null {
  const q = query.trim().toLowerCase();
  if (!q) return null;
  const out = new Set<string>();
  for (const n of nodes) {
    if (n.title.toLowerCase().includes(q)) out.add(n.id);
  }
  return out;
}

/** First matching node id in `nodes` order, or null when nothing matches. */
export function firstSearchMatch(
  query: string,
  nodes: Array<{ id: string; title: string }>,
): string | null {
  const q = query.trim().toLowerCase();
  if (!q) return null;
  for (const n of nodes) {
    if (n.title.toLowerCase().includes(q)) return n.id;
  }
  return null;
}

export interface Mover {
  id: string;
  deltaPts: number;
}

/** Same visibility threshold as the in-graph delta labels (in points). */
export const MOVER_MIN_DELTA_PTS = 0.05;

/**
 * The `count` nodes with the largest |deltaPts|, descending; ties keep the
 * input order. Deltas too small to earn an in-graph label are excluded so
 * the strip never disagrees with the graph.
 */
export function topMovers(deltas: Mover[], count = 5): Mover[] {
  return deltas
    .filter((d) => Number.isFinite(d.deltaPts) && Math.abs(d.deltaPts) >= MOVER_MIN_DELTA_PTS)
    .map((d, i) => ({ d, i }))
    .sort((a, b) => Math.abs(b.d.deltaPts) - Math.abs(a.d.deltaPts) || a.i - b.i)
    .slice(0, Math.max(0, count))
    .map((x) => x.d);
}

/**
 * First node (in `nodeIds` order) with no parents; falls back to the first
 * node when every node has a parent (cycles). Null on an empty graph.
 */
export function firstRootId(nodeIds: string[], edges: FlowEdge[]): string | null {
  if (nodeIds.length === 0) return null;
  const ids = new Set(nodeIds);
  const hasParent = new Set(
    edges
      .filter((e) => e.source !== e.target && ids.has(e.source) && ids.has(e.target))
      .map((e) => e.target),
  );
  return nodeIds.find((id) => !hasParent.has(id)) ?? nodeIds[0] ?? null;
}
