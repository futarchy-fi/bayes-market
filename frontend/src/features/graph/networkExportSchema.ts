import type { MarketStatus, CliqueSummary } from "@/lib/api/types";

/** Schema version — bump on breaking changes */
export const NETWORK_EXPORT_VERSION = 1;

export interface NetworkExportNode {
  id: string;
  title: string;
  status: MarketStatus;
  liquidity: number;
  volume: number;
  expires_at: string;
  /** Layout position at time of export */
  position: { x: number; y: number };
}

export interface NetworkExportEdge {
  source: string;
  target: string;
  /** "clique" for edges derived from cliques, "conditional" for user-added */
  type: "clique" | "conditional";
}

export interface NetworkExportSchema {
  version: number;
  exportedAt: string;
  metadata: {
    nodeCount: number;
    edgeCount: number;
    cliqueCount: number;
  };
  nodes: NetworkExportNode[];
  edges: NetworkExportEdge[];
  cliques: CliqueSummary[];
}
