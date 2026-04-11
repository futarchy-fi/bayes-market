import type { MarketSummary, CliqueSummary } from "@/lib/api/types";
import type { GraphEdge } from "./deriveEdges";
import {
  NETWORK_EXPORT_VERSION,
  type NetworkExportSchema,
  type NetworkExportNode,
  type NetworkExportEdge,
} from "./networkExportSchema";

interface GraphNodePosition {
  id: string;
  x: number;
  y: number;
}

/**
 * Build a NetworkExportSchema from the current graph state.
 */
export function buildNetworkExport(
  markets: MarketSummary[],
  nodes: GraphNodePosition[],
  cliqueEdges: GraphEdge[],
  conditionalEdges: Array<{ from: string; to: string }>,
  cliques: CliqueSummary[],
): NetworkExportSchema {
  const posMap = new Map(nodes.map((n) => [n.id, { x: n.x, y: n.y }]));

  const exportNodes: NetworkExportNode[] = markets.map((m) => ({
    id: m.id,
    title: m.title,
    status: m.status,
    liquidity: m.liquidity,
    volume: m.volume,
    expires_at: m.expires_at,
    position: posMap.get(m.id) ?? { x: 0, y: 0 },
  }));

  const exportEdges: NetworkExportEdge[] = [
    ...cliqueEdges.map(
      (e): NetworkExportEdge => ({ source: e.source, target: e.target, type: "clique" }),
    ),
    ...conditionalEdges.map(
      (e): NetworkExportEdge => ({ source: e.from, target: e.to, type: "conditional" }),
    ),
  ];

  return {
    version: NETWORK_EXPORT_VERSION,
    exportedAt: new Date().toISOString(),
    metadata: {
      nodeCount: exportNodes.length,
      edgeCount: exportEdges.length,
      cliqueCount: cliques.length,
    },
    nodes: exportNodes,
    edges: exportEdges,
    cliques,
  };
}

/**
 * Trigger a JSON file download in the browser.
 */
export function downloadJson(data: NetworkExportSchema, filename: string): void {
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
