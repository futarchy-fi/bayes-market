import type { CliqueSummary } from "@/lib/api/types";

export interface GraphEdge {
  source: string;
  target: string;
}

/**
 * Derive undirected edges from clique co-membership.
 * Any two nodes sharing a clique get an edge.
 * Edges are deduplicated (sorted pair key).
 */
export function deriveEdgesFromCliques(cliques: CliqueSummary[]): GraphEdge[] {
  const seen = new Set<string>();
  const edges: GraphEdge[] = [];

  for (const clique of cliques) {
    const nodes = clique.nodes;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]!;
        const b = nodes[j]!;
        const key = a < b ? `${a}::${b}` : `${b}::${a}`;
        if (!seen.has(key)) {
          seen.add(key);
          edges.push({ source: a, target: b });
        }
      }
    }
  }

  return edges;
}

/**
 * Remap edge endpoints from engine variableIds to market ids.
 * Endpoints already in market-id space pass through unchanged; edges with
 * an endpoint in neither space are dropped so downstream consumers
 * (d3 forceLink in particular) never see an unknown node id.
 */
export function remapEdgesToMarketIds(
  edges: GraphEdge[],
  markets: Array<{ id: string; variableId?: string }>,
): GraphEdge[] {
  const byVariableId = new Map<string, string>();
  const marketIds = new Set<string>();
  for (const m of markets) {
    marketIds.add(m.id);
    if (m.variableId) byVariableId.set(m.variableId, m.id);
  }

  const seen = new Set<string>();
  const remapped: GraphEdge[] = [];
  for (const e of edges) {
    const source = byVariableId.get(e.source) ?? e.source;
    const target = byVariableId.get(e.target) ?? e.target;
    if (source === target || !marketIds.has(source) || !marketIds.has(target)) continue;
    const key = source < target ? `${source}::${target}` : `${target}::${source}`;
    if (seen.has(key)) continue;
    seen.add(key);
    remapped.push({ source, target });
  }
  return remapped;
}

/**
 * Merge clique-derived edges with optional conditional edges.
 * Conditional edges are directional (from -> to) but stored in the same format.
 */
export function mergeEdges(
  cliqueEdges: GraphEdge[],
  conditionalEdges: Array<{ from: string; to: string }> = [],
): GraphEdge[] {
  const seen = new Set<string>(
    cliqueEdges.map((e) => {
      const a = typeof e.source === "string" ? e.source : e.source;
      const b = typeof e.target === "string" ? e.target : e.target;
      return a < b ? `${a}::${b}` : `${b}::${a}`;
    }),
  );

  const merged = [...cliqueEdges];

  for (const ce of conditionalEdges) {
    const key = ce.from < ce.to ? `${ce.from}::${ce.to}` : `${ce.to}::${ce.from}`;
    if (!seen.has(key)) {
      seen.add(key);
      merged.push({ source: ce.from, target: ce.to });
    }
  }

  return merged;
}
