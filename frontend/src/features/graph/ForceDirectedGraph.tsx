import { useMemo, useEffect, useRef } from "react";
import { useMarkets, useMarket, useEngineStats } from "@/lib/query/hooks";
import { formatProbability } from "@/lib/utils/format";
import { useForceGraph } from "./useForceGraph";
import { deriveEdgesFromCliques, mergeEdges } from "./deriveEdges";
import { select } from "d3-selection";
import { zoom as d3Zoom, zoomIdentity } from "d3-zoom";
import { drag as d3Drag } from "d3-drag";
import type { MarketSummary, CliqueSummary } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GraphEdge {
  from: string;
  to: string;
  label?: string;
}

interface ForceDirectedGraphProps {
  focusMarketId?: string;
  conditionalEdges?: GraphEdge[];
  onNodeClick?: (marketId: string) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NODE_W = 160;
const NODE_H = 72;
const SVG_WIDTH = 600;
const SVG_HEIGHT = 400;

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MarketNode({
  x,
  y,
  node,
  isFocus,
  isDimmed,
  detail,
  onClick,
}: {
  x: number;
  y: number;
  node: { id: string; title: string; status: string };
  isFocus: boolean;
  isDimmed: boolean;
  detail?: { marginals: Record<string, number>; outcomes: Array<{ id: string; name: string }> };
  onClick?: () => void;
}) {
  const borderColor = isFocus ? "var(--color-primary)" : "var(--color-border)";
  const bg = isFocus ? "var(--color-bg-surface)" : "var(--color-bg)";
  const truncatedTitle = node.title.length > 28 ? node.title.slice(0, 26) + "\u2026" : node.title;

  return (
    <g
      transform={`translate(${x - NODE_W / 2}, ${y - NODE_H / 2})`}
      style={{ cursor: onClick ? "pointer" : "default", opacity: isDimmed ? 0.3 : 1 }}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(); } : undefined}
      data-node-id={node.id}
    >
      <rect
        width={NODE_W}
        height={NODE_H}
        rx={8}
        fill={bg}
        stroke={borderColor}
        strokeWidth={isFocus ? 2.5 : 1}
      />
      <text
        x={NODE_W / 2}
        y={18}
        textAnchor="middle"
        fontSize="11"
        fontWeight={600}
        fill="var(--color-text)"
      >
        {truncatedTitle}
      </text>
      {detail && detail.outcomes.length > 0 && (
        <g transform="translate(8, 28)">
          {detail.outcomes.slice(0, 3).map((o, i) => {
            const p = detail.marginals[o.id] ?? 0;
            const barW = NODE_W - 16;
            return (
              <g key={o.id} transform={`translate(0, ${i * 14})`}>
                <rect width={barW} height={10} rx={3} fill="var(--color-border)" opacity={0.3} />
                <rect
                  width={Math.max(2, barW * p)}
                  height={10}
                  rx={3}
                  fill={p > 0.5 ? "var(--color-success)" : "var(--color-info)"}
                  opacity={0.7}
                />
                <text x={4} y={8} fontSize="8" fill="var(--color-text)" fontWeight={500}>
                  {o.name}: {formatProbability(p)}
                </text>
              </g>
            );
          })}
        </g>
      )}
      {/* Status dot */}
      <circle
        cx={NODE_W - 10}
        cy={10}
        r={4}
        fill={
          node.status === "active"
            ? "var(--color-success)"
            : node.status === "resolved"
              ? "var(--color-info)"
              : "var(--color-text-muted)"
        }
      />
    </g>
  );
}

function EdgeLine({
  x1,
  y1,
  x2,
  y2,
  isHighlighted,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  isHighlighted: boolean;
}) {
  return (
    <line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke="var(--color-primary)"
      strokeWidth={isHighlighted ? 2 : 1.5}
      strokeDasharray={isHighlighted ? "none" : "6 3"}
      opacity={isHighlighted ? 0.8 : 0.4}
    />
  );
}

function CliqueOverlay({
  clique,
  nodePositions,
}: {
  clique: CliqueSummary;
  nodePositions: Map<string, { x: number; y: number }>;
}) {
  const memberPositions = clique.nodes
    .map((id) => nodePositions.get(id))
    .filter((p): p is { x: number; y: number } => p != null);

  if (memberPositions.length < 2) return null;

  const pad = 20;
  const xs = memberPositions.map((p) => p.x);
  const ys = memberPositions.map((p) => p.y);
  const minX = Math.min(...xs) - NODE_W / 2 - pad;
  const minY = Math.min(...ys) - NODE_H / 2 - pad;
  const maxX = Math.max(...xs) + NODE_W / 2 + pad;
  const maxY = Math.max(...ys) + NODE_H / 2 + pad;

  return (
    <g>
      <rect
        x={minX}
        y={minY}
        width={maxX - minX}
        height={maxY - minY}
        rx={12}
        fill="var(--color-primary)"
        fillOpacity={0.06}
        stroke="var(--color-primary)"
        strokeWidth={1}
        strokeDasharray="4 4"
        strokeOpacity={0.3}
      />
      <text x={minX + 6} y={minY + 14} fontSize="9" fill="var(--color-primary)" opacity={0.7}>
        Clique {clique.id}
      </text>
    </g>
  );
}

function NodeWithDetail({
  x,
  y,
  node,
  isFocus,
  isDimmed,
  onClick,
}: {
  x: number;
  y: number;
  node: { id: string; title: string; status: string };
  isFocus: boolean;
  isDimmed: boolean;
  onClick?: () => void;
}) {
  const { data } = useMarket(node.id);
  const detail = data
    ? { marginals: data.market.marginals, outcomes: data.market.outcomes }
    : undefined;
  return (
    <MarketNode
      x={x}
      y={y}
      node={node}
      isFocus={isFocus}
      isDimmed={isDimmed}
      detail={detail}
      onClick={onClick}
    />
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ForceDirectedGraph({
  focusMarketId,
  conditionalEdges = [],
  onNodeClick,
}: ForceDirectedGraphProps) {
  const { data: marketsData, isLoading } = useMarkets();
  const { data: engineStats } = useEngineStats(focusMarketId ?? "", { enabled: !!focusMarketId });

  const markets = marketsData?.markets ?? [];
  const cliques = engineStats?.cliques.cliques ?? [];

  // Derive force graph input nodes
  const forceInputNodes = useMemo(
    () => markets.map((m: MarketSummary) => ({ id: m.id, title: m.title, status: m.status })),
    [markets],
  );

  // Derive edges from cliques + conditional edges
  const forceInputLinks = useMemo(() => {
    const cliqueEdges = deriveEdgesFromCliques(cliques);
    return mergeEdges(cliqueEdges, conditionalEdges);
  }, [cliques, conditionalEdges]);

  const graphOptions = useMemo(() => ({ width: SVG_WIDTH, height: SVG_HEIGHT }), []);
  const { positions, getSimulation, getNodes, flushPositions } = useForceGraph(
    forceInputNodes,
    forceInputLinks,
    graphOptions,
  );

  // Build position lookup
  const nodePositionMap = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    for (const np of positions.nodes) {
      map.set(np.id, { x: np.x, y: np.y });
    }
    return map;
  }, [positions]);

  // Focus-connected set: focusMarketId + all nodes sharing an edge with it
  const connectedToFocus = useMemo(() => {
    if (!focusMarketId) return null;
    const set = new Set<string>([focusMarketId]);
    for (const link of forceInputLinks) {
      const src = typeof link.source === "string" ? link.source : link.source;
      const tgt = typeof link.target === "string" ? link.target : link.target;
      if (src === focusMarketId) set.add(tgt);
      if (tgt === focusMarketId) set.add(src);
    }
    return set;
  }, [focusMarketId, forceInputLinks]);

  // --- Zoom behavior ---
  const svgRef = useRef<SVGSVGElement>(null);
  const gRef = useRef<SVGGElement>(null);

  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl) return;

    const zoomBehavior = d3Zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => {
        if (gRef.current) {
          gRef.current.setAttribute("transform", event.transform.toString());
        }
      });

    const sel = select(svgEl);
    sel.call(zoomBehavior);

    // Double-click to reset zoom
    sel.on("dblclick.zoom", () => {
      sel.call(zoomBehavior.transform, zoomIdentity);
    });

    return () => {
      sel.on(".zoom", null);
    };
  }, []);

  // --- Drag behavior ---
  useEffect(() => {
    const svgEl = svgRef.current;
    if (!svgEl || markets.length === 0) return;

    const nodeGroups = select(svgEl).selectAll<SVGGElement, unknown>("g[data-node-id]");

    const dragBehavior = d3Drag<SVGGElement, unknown>()
      .on("start", function (event) {
        const nodeId = this.getAttribute("data-node-id");
        if (!nodeId) return;
        const sim = getSimulation();
        const nodes = getNodes();
        const node = nodes.find((n) => n.id === nodeId);
        if (!node || !sim) return;
        if (!event.active) sim.alphaTarget(0.3).restart();
        node.fx = node.x;
        node.fy = node.y;
      })
      .on("drag", function (event) {
        const nodeId = this.getAttribute("data-node-id");
        if (!nodeId) return;
        const nodes = getNodes();
        const node = nodes.find((n) => n.id === nodeId);
        if (!node) return;
        node.fx = event.x;
        node.fy = event.y;
        flushPositions();
      })
      .on("end", function (event) {
        const nodeId = this.getAttribute("data-node-id");
        if (!nodeId) return;
        const sim = getSimulation();
        const nodes = getNodes();
        const node = nodes.find((n) => n.id === nodeId);
        if (!node || !sim) return;
        if (!event.active) sim.alphaTarget(0);
        node.fx = null;
        node.fy = null;
      });

    nodeGroups.call(dragBehavior);

    return () => {
      nodeGroups.on(".drag", null);
    };
  }, [positions, markets.length, getSimulation, getNodes, flushPositions]);

  // --- Loading state ---
  if (isLoading) {
    return (
      <div style={panelStyle}>
        <div style={{ color: "var(--color-text-muted)", textAlign: "center", padding: "var(--space-lg)" }}>
          Loading network...
        </div>
      </div>
    );
  }

  if (markets.length === 0) {
    return (
      <div style={panelStyle}>
        <div style={{ color: "var(--color-text-muted)", textAlign: "center" }}>
          No markets to visualize.
        </div>
      </div>
    );
  }

  // Resolve link endpoints to positions
  const resolvedLinks = forceInputLinks
    .map((link) => {
      const src = typeof link.source === "string" ? link.source : link.source;
      const tgt = typeof link.target === "string" ? link.target : link.target;
      const srcPos = nodePositionMap.get(src);
      const tgtPos = nodePositionMap.get(tgt);
      if (!srcPos || !tgtPos) return null;
      const isHighlighted = focusMarketId != null && (src === focusMarketId || tgt === focusMarketId);
      return { src, tgt, srcPos, tgtPos, isHighlighted };
    })
    .filter((l): l is NonNullable<typeof l> => l != null);

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-sm)" }}>
        <h3 style={{ fontSize: "1rem", fontWeight: 600 }}>
          Bayesian Network
        </h3>
        <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          {markets.length} variable{markets.length !== 1 ? "s" : ""}
          {conditionalEdges.length > 0 && ` \u00B7 ${conditionalEdges.length} edge${conditionalEdges.length !== 1 ? "s" : ""}`}
          {cliques.length > 0 && ` \u00B7 ${cliques.length} clique${cliques.length !== 1 ? "s" : ""}`}
          {engineStats && ` \u00B7 JT width ${engineStats.cliques.junction_tree_width}`}
        </div>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        style={{ width: "100%", height: "auto", minHeight: 200, maxHeight: 400 }}
      >
        <g ref={gRef}>
          {/* Clique overlays (behind edges/nodes) */}
          {cliques.map((c) => (
            <CliqueOverlay key={c.id} clique={c} nodePositions={nodePositionMap} />
          ))}

          {/* Edges */}
          {resolvedLinks.map((link, i) => (
            <EdgeLine
              key={`${link.src}-${link.tgt}-${i}`}
              x1={link.srcPos.x}
              y1={link.srcPos.y}
              x2={link.tgtPos.x}
              y2={link.tgtPos.y}
              isHighlighted={link.isHighlighted}
            />
          ))}

          {/* Market nodes */}
          {forceInputNodes.map((node) => {
            const pos = nodePositionMap.get(node.id);
            if (!pos) return null;
            const isFocus = node.id === focusMarketId;
            const isDimmed = connectedToFocus != null && !connectedToFocus.has(node.id);
            return (
              <NodeWithDetail
                key={node.id}
                x={pos.x}
                y={pos.y}
                node={node}
                isFocus={isFocus}
                isDimmed={isDimmed}
                onClick={onNodeClick ? () => onNodeClick(node.id) : undefined}
              />
            );
          })}
        </g>
      </svg>

      {/* Legend */}
      <div style={{ display: "flex", gap: "var(--space-md)", fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "var(--space-sm)" }}>
        <span>
          <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "var(--color-success)", marginRight: 4 }} />
          Active
        </span>
        <span>
          <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "var(--color-info)", marginRight: 4 }} />
          Resolved
        </span>
        {conditionalEdges.length > 0 && (
          <span>
            <span style={{ display: "inline-block", width: 16, height: 2, background: "var(--color-primary)", marginRight: 4, verticalAlign: "middle" }} />
            Conditional dependency
          </span>
        )}
        {cliques.length > 0 && (
          <span>
            <span style={{ display: "inline-block", width: 12, height: 12, border: "1px dashed var(--color-primary)", borderRadius: 3, marginRight: 4, verticalAlign: "middle", opacity: 0.5 }} />
            Junction tree clique
          </span>
        )}
      </div>
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};
