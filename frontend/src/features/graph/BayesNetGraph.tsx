import { useMemo } from "react";
import { useMarkets, useMarket, useEngineStats } from "@/lib/query/hooks";
import { formatProbability } from "@/lib/utils/format";
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
const PADDING = 40;

function layoutNodes(markets: MarketSummary[], focusId?: string): GraphNode[] {
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
}: {
  node: GraphNode;
  isFocus: boolean;
  detail?: { marginals: Record<string, number>; outcomes: Array<{ id: string; name: string }> };
}) {
  const borderColor = isFocus ? "var(--color-primary)" : "var(--color-border)";
  const bg = isFocus ? "var(--color-bg-surface)" : "var(--color-bg)";

  return (
    <g transform={`translate(${node.x - NODE_W / 2}, ${node.y - NODE_H / 2})`}>
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
}: {
  node: GraphNode;
  isFocus: boolean;
}) {
  const { data } = useMarket(node.id);
  const detail = data
    ? { marginals: data.market.marginals, outcomes: data.market.outcomes }
    : undefined;
  return <MarketNode node={node} isFocus={isFocus} detail={detail} />;
}

export function BayesNetGraph({
  focusMarketId,
  conditionalEdges = [],
}: BayesNetGraphProps) {
  const { data: marketsData, isLoading } = useMarkets();
  const { data: engineStats } = useEngineStats(focusMarketId ?? "", { enabled: !!focusMarketId });

  const markets = marketsData?.markets ?? [];
  const nodes = useMemo(() => layoutNodes(markets, focusMarketId), [markets, focusMarketId]);
  const cliques = engineStats?.cliques.cliques ?? [];

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
          Bayesian Network
        </h3>
        <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          {markets.length} variable{markets.length !== 1 ? "s" : ""}
          {conditionalEdges.length > 0 && ` · ${conditionalEdges.length} edge${conditionalEdges.length !== 1 ? "s" : ""}`}
          {cliques.length > 0 && ` · ${cliques.length} clique${cliques.length !== 1 ? "s" : ""}`}
          {engineStats && ` · JT width ${engineStats.cliques.junction_tree_width}`}
        </div>
      </div>

      <svg
        viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
        style={{ width: "100%", height: "auto", minHeight: 200, maxHeight: 400 }}
      >
        {/* Clique overlays (behind edges/nodes) */}
        {cliques.map((c) => (
          <CliqueOverlay key={c.id} clique={c} nodes={nodes} />
        ))}

        {/* Conditional edges */}
        {conditionalEdges.map((e, i) => (
          <EdgeLine key={`${e.from}-${e.to}-${i}`} from={e.from} to={e.to} nodes={nodes} />
        ))}

        {/* Market nodes */}
        {nodes.map((node) => (
          <NodeWithDetail
            key={node.id}
            node={node}
            isFocus={node.id === focusMarketId}
          />
        ))}
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
