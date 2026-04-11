import { useMemo, useEffect, useRef, useState, useCallback } from "react";
import { useMarkets, useMarket, useEngineStats } from "@/lib/query/hooks";
import { formatProbability } from "@/lib/utils/format";
import { useAssumptions } from "@/features/assumptions/AssumptionContext";
import { useAnimationPropagation } from "./useAnimationPropagation";
import { deriveEdgesFromCliques, mergeEdges } from "./deriveEdges";
import { buildNetworkExport, downloadJson } from "./networkExport";
import { readAndValidateFile } from "./networkImport";
import type { NetworkExportSchema } from "./networkExportSchema";
import type { MarketSummary } from "@/lib/api/types";

interface GraphNode {
  id: string;
  title: string;
  x: number;
  y: number;
  marginals: Record<string, number>;
  outcomeName: string;
  status: string;
}

interface GraphEdge {
  from: string;
  to: string;
  label?: string;
}

interface BayesNetGraphProps {
  /** The currently viewed market — highlighted in the graph */
  focusMarketId?: string;
  /** Edges derived from conditional edits */
  conditionalEdges?: GraphEdge[];
}

const NODE_W = 160;
const NODE_H = 72;
const PADDING = 60;

function layoutNodes(markets: MarketSummary[]): GraphNode[] {
  // Arrange in a circle for small N, grid for larger
  const n = markets.length;
  if (n === 0) return [];

  const cx = 300;
  const cy = 200;
  const radius = Math.max(120, n * 40);

  return markets.map((m, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2;
    return {
      id: m.id,
      title: m.title.length > 28 ? m.title.slice(0, 26) + "…" : m.title,
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
      marginals: {},
      outcomeName: "",
      status: m.status,
    };
  });
}

function MarketNode({
  node,
  isFocus,
  detail,
  animationClass,
}: {
  node: GraphNode;
  isFocus: boolean;
  detail?: { marginals: Record<string, number>; outcomes: Array<{ id: string; name: string }> };
  animationClass?: string;
}) {
  const borderColor = isFocus ? "var(--color-primary)" : "var(--color-border)";
  const bg = isFocus ? "var(--color-bg-surface)" : "var(--color-bg)";

  return (
    <g
      transform={`translate(${node.x - NODE_W / 2}, ${node.y - NODE_H / 2})`}
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
      >
        {node.title}
      </text>
      {/* Mini probability bars */}
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

function EdgeLine({ from, to, nodes }: { from: string; to: string; nodes: GraphNode[] }) {
  const a = nodes.find((n) => n.id === from);
  const b = nodes.find((n) => n.id === to);
  if (!a || !b) return null;

  // Arrow from a → b
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (dist === 0) return null;

  const ux = dx / dist;
  const uy = dy / dist;

  // Start/end offset by node radius
  const startX = a.x + ux * (NODE_W / 2 + 4);
  const startY = a.y + uy * (NODE_H / 2 + 4);
  const endX = b.x - ux * (NODE_W / 2 + 8);
  const endY = b.y - uy * (NODE_H / 2 + 8);

  return (
    <g>
      <line
        x1={startX}
        y1={startY}
        x2={endX}
        y2={endY}
        stroke="var(--color-primary)"
        strokeWidth={1.5}
        strokeDasharray="6 3"
        opacity={0.6}
      />
      {/* Arrowhead */}
      <polygon
        points={`${endX},${endY} ${endX - ux * 8 - uy * 4},${endY - uy * 8 + ux * 4} ${endX - ux * 8 + uy * 4},${endY - uy * 8 - ux * 4}`}
        fill="var(--color-primary)"
        opacity={0.6}
      />
    </g>
  );
}

function CliqueOverlay({
  clique,
  nodes,
}: {
  clique: { id: string; nodes: string[] };
  nodes: GraphNode[];
}) {
  const memberNodes = nodes.filter((n) => clique.nodes.includes(n.id));
  if (memberNodes.length < 2) return null;

  // Draw a rounded rectangle around the clique members
  const xs = memberNodes.map((n) => n.x);
  const ys = memberNodes.map((n) => n.y);
  const pad = 20;
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

/** Renders a mini detail-fetcher node that uses useMarket */
function NodeWithDetail({
  node,
  isFocus,
  animationClass,
}: {
  node: GraphNode;
  isFocus: boolean;
  animationClass?: string;
}) {
  const { data } = useMarket(node.id);
  const detail = data
    ? { marginals: data.market.marginals, outcomes: data.market.outcomes }
    : undefined;
  return <MarketNode node={node} isFocus={isFocus} detail={detail} animationClass={animationClass} />;
}

export function BayesNetGraph({
  focusMarketId,
  conditionalEdges = [],
}: BayesNetGraphProps) {
  const { data: marketsData, isLoading } = useMarkets();
  const { data: engineStats } = useEngineStats(focusMarketId ?? "", { enabled: !!focusMarketId });

  // --- Snapshot state for imported networks ---
  const [snapshot, setSnapshot] = useState<NetworkExportSchema | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const liveMarkets = marketsData?.markets ?? [];
  const markets = snapshot
    ? snapshot.nodes.map((n) => ({
        id: n.id,
        title: n.title,
        status: n.status,
        liquidity: n.liquidity,
        volume: n.volume,
        expires_at: n.expires_at,
      }))
    : liveMarkets;

  const nodes = useMemo(
    () =>
      snapshot
        ? snapshot.nodes.map((n) => ({
            id: n.id,
            title: n.title.length > 28 ? n.title.slice(0, 26) + "…" : n.title,
            x: n.position.x,
            y: n.position.y,
            marginals: {} as Record<string, number>,
            outcomeName: "",
            status: n.status,
          }))
        : layoutNodes(liveMarkets),
    [snapshot, liveMarkets],
  );
  const cliques = snapshot ? snapshot.cliques : (engineStats?.cliques.cliques ?? []);

  // --- Animation: detect assumption changes and trigger propagation ---
  const { assumptions } = useAssumptions();
  const { animatingNodes, animatingEdges, evidenceNodeId, triggerAnimation, cancelAnimation } =
    useAnimationPropagation();
  const prevAssumptionsRef = useRef(assumptions);

  // Derive all edges for BFS traversal (clique-derived + conditional)
  const allEdges = useMemo(
    () => mergeEdges(deriveEdgesFromCliques(cliques), conditionalEdges),
    [cliques, conditionalEdges],
  );

  useEffect(() => {
    const prev = prevAssumptionsRef.current;
    prevAssumptionsRef.current = assumptions;

    if (prev === assumptions) return;

    // Find the assumption that was added or removed
    const added = assumptions.find(
      (a) => !prev.some((p) => p.variableId === a.variableId && p.outcomeId === a.outcomeId),
    );
    const removed = prev.find(
      (p) => !assumptions.some((a) => a.variableId === p.variableId && a.outcomeId === p.outcomeId),
    );

    const changedVariableId = added?.variableId ?? removed?.variableId;
    if (!changedVariableId) return;

    // Find the node (market) that corresponds to the changed variable.
    // Assumption variableId may match market id (MarketSummary only has id).
    const evidenceNode = markets.find((m) => m.id === changedVariableId);
    if (evidenceNode && allEdges.length > 0) {
      triggerAnimation(evidenceNode.id, allEdges);
    }
  }, [assumptions, markets, allEdges, triggerAnimation]);

  // Cancel animation on unmount
  useEffect(() => cancelAnimation, [cancelAnimation]);

  // --- Export handler ---
  const handleExport = useCallback(() => {
    const cliqueEdges = deriveEdgesFromCliques(cliques);
    const data = buildNetworkExport(markets as MarketSummary[], nodes, cliqueEdges, conditionalEdges, cliques);
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadJson(data, `bayes-network-${ts}.json`);
  }, [markets, nodes, cliques, conditionalEdges]);

  // --- Import handler ---
  const handleImportFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportError(null);
    const result = await readAndValidateFile(file);
    if (result.ok) {
      setSnapshot(result.data);
    } else {
      setImportError(result.error);
    }
    // Reset so the same file can be re-selected
    e.target.value = "";
  }, []);

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

  // Compute SVG viewBox from node positions
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const vbX = Math.min(...xs) - NODE_W / 2 - PADDING;
  const vbY = Math.min(...ys) - NODE_H / 2 - PADDING;
  const vbW = Math.max(...xs) - Math.min(...xs) + NODE_W + PADDING * 2;
  const vbH = Math.max(...ys) - Math.min(...ys) + NODE_H + PADDING * 2;

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-sm)" }}>
        <h3 style={{ fontSize: "1rem", fontWeight: 600 }}>
          Bayesian Network{snapshot ? " (imported)" : ""}
        </h3>

        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)" }}>
          {/* Export / Import buttons */}
          <div style={{ display: "flex", gap: 4 }}>
            <button
              type="button"
              onClick={handleExport}
              style={smallButtonStyle}
              title="Export network as JSON"
            >
              Export
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              style={smallButtonStyle}
              title="Import network from JSON"
            >
              Import
            </button>
            {snapshot && (
              <button
                type="button"
                onClick={() => { setSnapshot(null); setImportError(null); }}
                style={{ ...smallButtonStyle, color: "var(--color-danger)" }}
                title="Return to live network"
              >
                Clear
              </button>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              style={{ display: "none" }}
              onChange={handleImportFile}
            />
          </div>

          <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
            {markets.length} variable{markets.length !== 1 ? "s" : ""}
            {conditionalEdges.length > 0 && ` · ${conditionalEdges.length} edge${conditionalEdges.length !== 1 ? "s" : ""}`}
            {cliques.length > 0 && ` · ${cliques.length} clique${cliques.length !== 1 ? "s" : ""}`}
            {engineStats && !snapshot && ` · JT width ${engineStats.cliques.junction_tree_width}`}
          </div>
        </div>
      </div>

      {importError && (
        <div style={{ fontSize: "0.75rem", color: "var(--color-danger)", marginBottom: "var(--space-sm)" }}>
          Import failed: {importError}
        </div>
      )}

      <svg
        viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
        style={{ width: "100%", height: "auto", minHeight: 200, maxHeight: 400 }}
      >
        <defs>
          {/* Glow filter for evidence node */}
          <filter id="evidence-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="6" result="blur" />
            <feFlood floodColor="var(--color-primary)" floodOpacity="0.6" result="color" />
            <feComposite in="color" in2="blur" operator="in" result="glow" />
            <feMerge>
              <feMergeNode in="glow" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          {/* Highlight filter for nodes reached by propagation wave */}
          <filter id="propagation-highlight" x="-15%" y="-15%" width="130%" height="130%">
            <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="var(--color-info)" floodOpacity="0.5" />
          </filter>
        </defs>
        <style>{`
          @keyframes evidence-pulse {
            0% { opacity: 0.7; }
            50% { opacity: 1; }
            100% { opacity: 0.7; }
          }
          @keyframes propagation-arrive {
            0% { opacity: 0; transform: scale(0.95); }
            50% { opacity: 1; transform: scale(1.02); }
            100% { opacity: 1; transform: scale(1); }
          }
          @keyframes edge-flow {
            0% { stroke-dashoffset: 16; }
            100% { stroke-dashoffset: 0; }
          }
          .evidence-node { animation: evidence-pulse 0.8s ease-in-out infinite; filter: url(#evidence-glow); }
          .propagation-node { animation: propagation-arrive 0.3s ease-out forwards; filter: url(#propagation-highlight); }
          .propagation-edge { animation: edge-flow 0.4s linear infinite; }
        `}</style>

        {/* Clique overlays (behind edges/nodes) */}
        {cliques.map((c) => (
          <CliqueOverlay key={c.id} clique={c} nodes={nodes} />
        ))}

        {/* Conditional edges */}
        {conditionalEdges.map((e, i) => (
          <EdgeLine key={`${e.from}-${e.to}-${i}`} from={e.from} to={e.to} nodes={nodes} />
        ))}

        {/* Animated propagation edges */}
        {animatingEdges.size > 0 && allEdges.map((e) => {
          const ek = e.source < e.target ? `${e.source}::${e.target}` : `${e.target}::${e.source}`;
          if (!animatingEdges.has(ek)) return null;
          const a = nodes.find((n) => n.id === e.source);
          const b = nodes.find((n) => n.id === e.target);
          if (!a || !b) return null;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist === 0) return null;
          const ux = dx / dist;
          const uy = dy / dist;
          const sx = a.x + ux * (NODE_W / 2 + 4);
          const sy = a.y + uy * (NODE_H / 2 + 4);
          const ex = b.x - ux * (NODE_W / 2 + 8);
          const ey = b.y - uy * (NODE_H / 2 + 8);
          return (
            <line
              key={`anim-${ek}`}
              x1={sx} y1={sy} x2={ex} y2={ey}
              stroke="var(--color-info)"
              strokeWidth={2.5}
              strokeDasharray="8 8"
              opacity={0.8}
              className="propagation-edge"
            />
          );
        })}

        {/* Market nodes */}
        {nodes.map((node) => {
          const isEvidence = node.id === evidenceNodeId;
          const isAnimating = animatingNodes.has(node.id);
          const animClass = isEvidence
            ? "evidence-node"
            : isAnimating
              ? "propagation-node"
              : undefined;
          return (
            <NodeWithDetail
              key={node.id}
              node={node}
              isFocus={node.id === focusMarketId}
              animationClass={animClass}
            />
          );
        })}
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

const smallButtonStyle: React.CSSProperties = {
  padding: "2px 8px",
  fontSize: "0.7rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  cursor: "pointer",
  fontWeight: 500,
};
