import { useMemo, useEffect, useRef } from "react";
import { useMarkets, useEngineStats, useNetwork, useGraphMarkets } from "@/lib/query/hooks";
import { isExchangeMode } from "@/lib/exchangeMode";
import { formatProbability } from "@/lib/utils/format";
import { useForceGraph } from "./useForceGraph";
import { useAnimationPropagation } from "./useAnimationPropagation";
import { deriveEdgesFromCliques, mergeEdges, remapEdgesToMarketIds } from "./deriveEdges";
import { select } from "d3-selection";
import { zoom as d3Zoom, zoomIdentity } from "d3-zoom";
import { drag as d3Drag } from "d3-drag";
import type { MarketSummary, CliqueSummary } from "@/lib/api/types";
import type { Assumption } from "@/features/assumptions/AssumptionContext";

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
  /** Pass assumptions from AssumptionContext to trigger propagation animations on change */
  assumptions?: Assumption[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const MAX_FORCE_NODES = 60;

const NODE_W = 160;
const NODE_H = 72;
const SVG_WIDTH = 600;
const SVG_HEIGHT = 400;

// ---------------------------------------------------------------------------
// Pure subgraph selection (zero extra queries, capped at MAX_FORCE_NODES)
// ---------------------------------------------------------------------------

function outcomeDisplayName(id: string): string {
  if (id === "yes") return "Yes";
  if (id === "no") return "No";
  return id;
}

function detailFromMarket(
  market: MarketSummary,
  conditionedMarginals?: Record<string, number>,
): { marginals: Record<string, number>; outcomes: Array<{ id: string; name: string }> } | undefined {
  const marginals = conditionedMarginals ?? market.marginals;
  if (!marginals || Object.keys(marginals).length === 0) return undefined;
  const outcomes =
    market.outcomes && market.outcomes.length > 0
      ? market.outcomes
      : Object.keys(marginals).map((id) => ({ id, name: outcomeDisplayName(id) }));
  return { marginals, outcomes };
}

export function selectForceSubgraph(
  markets: MarketSummary[],
  edges: Array<{ source: string; target: string }>,
  focusMarketId?: string,
  maxNodes = MAX_FORCE_NODES,
): {
  visibleMarkets: MarketSummary[];
  visibleEdges: Array<{ source: string; target: string }>;
  linkedCount: number;
} {
  const adjacency = new Map<string, Set<string>>();
  for (const m of markets) adjacency.set(m.id, new Set());
  for (const e of edges) {
    if (e.source === e.target) continue;
    adjacency.get(e.source)?.add(e.target);
    adjacency.get(e.target)?.add(e.source);
  }

  const linkedIds = markets.filter((m) => (adjacency.get(m.id)?.size ?? 0) > 0).map((m) => m.id);
  const linkedCount = linkedIds.length;

  if (markets.length <= maxNodes) {
    return { visibleMarkets: markets, visibleEdges: edges, linkedCount };
  }

  const degree = (id: string) => adjacency.get(id)?.size ?? 0;
  const marketById = new Map(markets.map((m) => [m.id, m]));
  const picked = new Set<string>();

  // Prefer BFS ego neighborhood around focusMarketId when available.
  if (focusMarketId && marketById.has(focusMarketId)) {
    const queue: string[] = [focusMarketId];
    picked.add(focusMarketId);
    while (queue.length > 0 && picked.size < maxNodes) {
      const current = queue.shift()!;
      const neighbors = Array.from(adjacency.get(current) ?? []).sort(
        (a, b) => degree(b) - degree(a) || (a < b ? -1 : a > b ? 1 : 0),
      );
      for (const next of neighbors) {
        if (picked.size >= maxNodes) break;
        if (!picked.has(next)) {
          picked.add(next);
          queue.push(next);
        }
      }
    }
  }

  // Fill with highest-degree linked nodes (e.g. if no focusMarketId or isolated focus).
  if (picked.size < maxNodes) {
    const byDegree = [...linkedIds].sort(
      (a, b) => degree(b) - degree(a) || (a < b ? -1 : a > b ? 1 : 0),
    );
    for (const id of byDegree) {
      if (picked.size >= maxNodes) break;
      picked.add(id);
    }
  }

  // Final fallback if the graph has fewer than maxNodes linked markets.
  if (picked.size < maxNodes) {
    for (const m of markets) {
      if (picked.size >= maxNodes) break;
      picked.add(m.id);
    }
  }

  const visibleMarkets = markets.filter((m) => picked.has(m.id));
  const visibleEdges = edges.filter((e) => picked.has(e.source) && picked.has(e.target));
  return { visibleMarkets, visibleEdges, linkedCount };
}

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
  animationClass,
}: {
  x: number;
  y: number;
  node: { id: string; title: string; status: string };
  isFocus: boolean;
  isDimmed: boolean;
  detail?: { marginals: Record<string, number>; outcomes: Array<{ id: string; name: string }> };
  onClick?: () => void;
  animationClass?: string;
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
      className={animationClass}
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
        style={{ userSelect: "none" }}
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
                  fill={animationClass ? "var(--color-info)" : p > 0.5 ? "var(--color-success)" : "var(--color-info)"}
                  opacity={animationClass ? 0.9 : 0.7}
                  style={{ transition: "width 0.3s ease, opacity 0.3s ease, fill 0.3s ease" }}
                />
                <text x={4} y={8} fontSize="8" fill="var(--color-text)" fontWeight={500} style={{ userSelect: "none" }}>
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

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ForceDirectedGraph({
  focusMarketId,
  conditionalEdges = [],
  onNodeClick,
  assumptions,
}: ForceDirectedGraphProps) {
  const exchangeMode = isExchangeMode();
  const { data: marketsData, isLoading } = useMarkets();
  const { data: engineStats } = useEngineStats(focusMarketId ?? "", {
    enabled: !!focusMarketId && !exchangeMode,
  });
  const { data: networkData } = useNetwork();

  const contextPayload = useMemo(
    () => (assumptions ?? []).map((a) => ({ variableId: a.variableId, outcomeId: a.outcomeId })),
    [assumptions],
  );
  const conditionedGraph = useGraphMarkets(contextPayload, { enabled: contextPayload.length > 0 });
  const conditionedById = useMemo(() => {
    const map = new Map<string, Record<string, number>>();
    for (const gm of conditionedGraph?.data?.markets ?? []) {
      if (gm.conditionalMarginals) {
        map.set(gm.id, gm.conditionalMarginals as unknown as Record<string, number>);
      }
    }
    return map;
  }, [conditionedGraph?.data]);

  const markets = marketsData?.markets ?? [];
  const cliques = engineStats?.cliques.cliques ?? [];

  // Animation propagation state
  const { animatingNodes, animatingEdges, evidenceNodeId, triggerAnimation, cancelAnimation } =
    useAnimationPropagation();

  // Cancel animation on unmount
  useEffect(() => cancelAnimation, [cancelAnimation]);

  // Edge base: the full network DAG when available (market-id space), else
  // the focused market's clique edges (variableId space).
  const allEdges = useMemo(() => {
    const networkEdges = (networkData?.edges ?? []).map((e) => ({ source: e.from, target: e.to }));
    const base = networkEdges.length > 0 ? networkEdges : deriveEdgesFromCliques(cliques);
    return remapEdgesToMarketIds(mergeEdges(base, conditionalEdges), markets);
  }, [networkData, cliques, conditionalEdges, markets]);

  const { visibleMarkets, visibleEdges, linkedCount } = useMemo(
    () => selectForceSubgraph(markets, allEdges, focusMarketId, MAX_FORCE_NODES),
    [markets, allEdges, focusMarketId],
  );

  // Derive force graph input nodes directly from visibleMarkets (no N+1 useMarket!)
  const forceInputNodes = useMemo(
    () =>
      visibleMarkets.map((m: MarketSummary) => ({
        id: m.id,
        title: m.title,
        status: m.status,
        variableId: m.variableId,
        market: m,
      })),
    [visibleMarkets],
  );
  const forceInputLinks = visibleEdges;

  // Detect assumption changes and trigger propagation animation
  const prevAssumptionsRef = useRef(assumptions);
  useEffect(() => {
    const prev = prevAssumptionsRef.current;
    prevAssumptionsRef.current = assumptions;
    if (!assumptions || !prev || prev === assumptions) return;

    const added = assumptions.find(
      (a) => !prev.some((p) => p.variableId === a.variableId && p.outcomeId === a.outcomeId),
    );
    const removed = prev.find(
      (p) => !assumptions.some((a) => a.variableId === p.variableId && a.outcomeId === p.outcomeId),
    );

    const changedVariableId = added?.variableId ?? removed?.variableId;
    if (!changedVariableId) return;

    const evidenceNode = visibleMarkets.find(
      (mk) => mk.id === changedVariableId || mk.variableId === changedVariableId,
    );
    if (evidenceNode && visibleEdges.length > 0) {
      triggerAnimation(evidenceNode.id, visibleEdges);
    }
  }, [assumptions, visibleMarkets, visibleEdges, triggerAnimation]);

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
      const src = link.source;
      const tgt = link.target;
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
    if (!svgEl || visibleMarkets.length === 0) return;

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
  }, [positions, visibleMarkets.length, getSimulation, getNodes, flushPositions]);

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
      const src = link.source;
      const tgt = link.target;
      const srcPos = nodePositionMap.get(src);
      const tgtPos = nodePositionMap.get(tgt);
      if (!srcPos || !tgtPos) return null;
      const isHighlighted = focusMarketId != null && (src === focusMarketId || tgt === focusMarketId);
      return { src, tgt, srcPos, tgtPos, isHighlighted };
    })
    .filter((l): l is NonNullable<typeof l> => l != null);

  const isCapped = visibleMarkets.length < markets.length;

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "var(--space-sm)", marginBottom: "var(--space-sm)" }}>
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

      {isCapped && (
        <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", marginBottom: "var(--space-xs)" }}>
          {linkedCount > visibleMarkets.length
            ? `Showing ${visibleMarkets.length} of ${linkedCount} linked markets`
            : `Showing ${visibleMarkets.length} of ${markets.length} markets`}
        </div>
      )}

      <svg
        ref={svgRef}
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        style={{ width: "100%", height: "auto", minHeight: 200, maxHeight: 400, userSelect: "none" }}
      >
        <defs>
          {/* Glow filter for evidence node */}
          <filter id="fdg-evidence-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="6" result="blur" />
            <feFlood floodColor="var(--color-primary)" floodOpacity="0.6" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="glow" />
            <feMerge>
              <feMergeNode in="glow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Highlight filter for nodes reached by propagation wave */}
          <filter id="fdg-propagation-highlight" x="-15%" y="-15%" width="130%" height="130%">
            <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="var(--color-info)" floodOpacity="0.5" />
          </filter>
        </defs>
        <style>{`
          @keyframes fdg-evidence-pulse {
            0% { opacity: 0.7; }
            50% { opacity: 1; }
            100% { opacity: 0.7; }
          }
          @keyframes fdg-propagation-arrive {
            0% { opacity: 0; transform: scale(0.95); }
            50% { opacity: 1; transform: scale(1.02); }
            100% { opacity: 1; transform: scale(1); }
          }
          @keyframes fdg-edge-flow {
            0% { stroke-dashoffset: 16; }
            100% { stroke-dashoffset: 0; }
          }
          .fdg-evidence-node { animation: fdg-evidence-pulse 0.8s ease-in-out infinite; filter: url(#fdg-evidence-glow); }
          .fdg-propagation-node { animation: fdg-propagation-arrive 0.3s ease-out forwards; filter: url(#fdg-propagation-highlight); }
          .fdg-propagation-edge { animation: fdg-edge-flow 0.4s linear infinite; }
        `}</style>
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

          {/* Animated propagation edges */}
          {animatingEdges.size > 0 && visibleEdges.map((e) => {
            const ek = e.source < e.target ? `${e.source}::${e.target}` : `${e.target}::${e.source}`;
            if (!animatingEdges.has(ek)) return null;
            const srcPos = nodePositionMap.get(e.source);
            const tgtPos = nodePositionMap.get(e.target);
            if (!srcPos || !tgtPos) return null;
            return (
              <line
                key={`anim-${ek}`}
                x1={srcPos.x}
                y1={srcPos.y}
                x2={tgtPos.x}
                y2={tgtPos.y}
                stroke="var(--color-info)"
                strokeWidth={2.5}
                strokeDasharray="8 8"
                opacity={0.8}
                className="fdg-propagation-edge"
              />
            );
          })}

          {/* Market nodes — rendered directly from already-loaded markets */}
          {forceInputNodes.map((node) => {
            const pos = nodePositionMap.get(node.id);
            if (!pos) return null;
            const isFocus = node.id === focusMarketId;
            const isDimmed = connectedToFocus != null && !connectedToFocus.has(node.id);
            const isEvidence = node.id === evidenceNodeId;
            const isAnimating = animatingNodes.has(node.id);
            const animClass = isEvidence
              ? "fdg-evidence-node"
              : isAnimating
                ? "fdg-propagation-node"
                : undefined;
            const detail = detailFromMarket(
              node.market,
              contextPayload.length > 0 ? conditionedById.get(node.id) : undefined,
            );
            return (
              <MarketNode
                key={node.id}
                x={pos.x}
                y={pos.y}
                node={node}
                isFocus={isFocus}
                isDimmed={isDimmed}
                detail={detail}
                onClick={onNodeClick ? () => onNodeClick(node.id) : undefined}
                animationClass={animClass}
              />
            );
          })}
        </g>
      </svg>

      {/* Legend */}
      <div style={{ display: "flex", gap: "var(--space-md)", fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "var(--space-sm)", flexWrap: "wrap" }}>
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
  minWidth: 0,
};
