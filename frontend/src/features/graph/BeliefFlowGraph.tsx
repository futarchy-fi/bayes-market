import { useMemo, useState, useCallback } from "react";
import { useMarkets, useMarket, useNetwork } from "@/lib/query/hooks";
import { useOptionalAssumptions } from "@/features/assumptions/AssumptionContext";
import { computeFlowLayout, wrapTitle, DEFAULT_FLOW_OPTIONS, type PositionedNode } from "./flowLayout";
import type { MarketSummary } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// The belief-flow view: a layered DAG read left-to-right as cause -> effect.
// One thin bar per node (P of the first outcome, shared 0-100 scale), full
// two-line titles, solid hairline edges with arrowheads, and — when
// assumptions are active — a signed delta against the unconditional prior.
// ---------------------------------------------------------------------------

const NODE_W = DEFAULT_FLOW_OPTIONS.nodeWidth;
const NODE_H = DEFAULT_FLOW_OPTIONS.nodeHeight;
const BAR_W = NODE_W - 102;
const BAR_H = 5;

interface BeliefFlowGraphProps {
  focusMarketId?: string;
  onNodeClick?: (marketId: string) => void;
}

interface FlowMarket {
  id: string;
  title: string;
  status: string;
  variableId?: string;
}

/** Left-square, right-rounded bar path (data-end rounded, baseline square). */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(h / 2, Math.max(0, w - 0.01));
  if (w <= r) return `M ${x} ${y} h ${Math.max(w, 0.5)} v ${h} h ${-Math.max(w, 0.5)} Z`;
  return [
    `M ${x} ${y}`,
    `h ${w - r}`,
    `a ${r} ${r} 0 0 1 ${r} ${r}`,
    h > 2 * r ? `v ${h - 2 * r}` : "",
    `a ${r} ${r} 0 0 1 ${-r} ${r}`,
    `h ${-(w - r)}`,
    `Z`,
  ].join(" ");
}

function firstOutcomeProbability(
  market: { outcomes: Array<{ id: string }>; marginals: Record<string, number> } | undefined,
): { outcomeId: string; p: number } | null {
  if (!market || market.outcomes.length === 0) return null;
  const preferred = market.outcomes.find((o) => o.id === "yes") ?? market.outcomes[0];
  if (!preferred) return null;
  const p = market.marginals[preferred.id];
  if (typeof p !== "number") return null;
  return { outcomeId: preferred.id, p };
}

function FlowNode({
  node,
  market,
  context,
  isFocus,
  assumedOutcome,
  onClick,
  onHover,
}: {
  node: PositionedNode;
  market: FlowMarket;
  context: Array<{ variableId: string; outcomeId: string }>;
  isFocus: boolean;
  assumedOutcome?: string;
  onClick?: () => void;
  onHover: (info: { id: string; x: number; y: number } | null) => void;
}) {
  const conditioned = useMarket(market.id, { context });
  const base = useMarket(market.id);

  const condP = firstOutcomeProbability(conditioned.data?.market);
  const baseP = firstOutcomeProbability(base.data?.market);
  const shown = condP ?? baseP;
  const hasDelta = context.length > 0 && condP != null && baseP != null;
  const delta = hasDelta ? condP.p - baseP.p : 0;
  const deltaPts = delta * 100;
  const showDelta = hasDelta && Math.abs(deltaPts) >= 0.05;

  const titleLines = wrapTitle(market.title, 30);
  const isResolved = market.status !== "active";

  return (
    <g
      transform={`translate(${node.x}, ${node.y})`}
      data-node-id={market.id}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(); } : undefined}
      onMouseEnter={() => onHover({ id: market.id, x: node.x, y: node.y })}
      onMouseLeave={() => onHover(null)}
      style={{ cursor: onClick ? "pointer" : "default", opacity: isResolved ? 0.45 : 1 }}
    >
      {/* Quiet hit/hover surface; a visible border only for the focused node */}
      <rect
        width={NODE_W}
        height={NODE_H}
        rx={6}
        fill={isFocus ? "var(--color-bg-surface)" : "transparent"}
        stroke={isFocus ? "var(--color-primary)" : "transparent"}
        strokeWidth={1.5}
      />

      {titleLines.map((line, i) => (
        <text
          key={i}
          x={10}
          y={17 + i * 13}
          fontSize="10.5"
          fontWeight={isFocus ? 700 : 600}
          fill="var(--color-text)"
        >
          {line}
        </text>
      ))}

      {/* Single probability bar: track + fill on a shared 0-100 scale */}
      <rect x={10} y={NODE_H - 19} width={BAR_W} height={BAR_H} rx={BAR_H / 2} fill="var(--color-border)" />
      {shown && shown.p > 0.004 && (
        <path
          d={barPath(10, NODE_H - 19, Math.max(2, shown.p * BAR_W), BAR_H)}
          fill="var(--color-info)"
        />
      )}
      {shown && (
        <text
          x={10 + BAR_W + 7}
          y={NODE_H - 13.5}
          fontSize="10.5"
          fontWeight={600}
          fill="var(--color-text)"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {(shown.p * 100).toFixed(1)}%
        </text>
      )}

      {/* Delta vs. the unconditional prior, on the bar line, right-aligned */}
      {showDelta && (
        <text
          x={NODE_W - 6}
          y={NODE_H - 13.5}
          textAnchor="end"
          fontSize="9.5"
          fontWeight={700}
          fill={deltaPts > 0 ? "var(--color-success)" : "var(--color-danger)"}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {deltaPts > 0 ? "▲" : "▼"}{Math.abs(deltaPts).toFixed(1)}
        </text>
      )}

      {/* Evidence badge for assumed variables */}
      {assumedOutcome && (
        <g transform={`translate(10, ${NODE_H - 10})`}>
          <rect width={58} height={11} rx={3} fill="var(--color-primary)" />
          <text x={29} y={8.5} textAnchor="middle" fontSize="7.5" fontWeight={700} fill="#fff">
            GIVEN: {assumedOutcome.toUpperCase()}
          </text>
        </g>
      )}
    </g>
  );
}

export function BeliefFlowGraph({ focusMarketId, onNodeClick }: BeliefFlowGraphProps) {
  const { data: marketsData, isLoading } = useMarkets();
  const { data: networkData } = useNetwork();
  const assumptionState = useOptionalAssumptions();
  const assumptions = assumptionState?.assumptions ?? [];

  const markets: FlowMarket[] = (marketsData?.markets ?? []).map((m: MarketSummary) => ({
    id: m.id,
    title: m.title,
    status: m.status,
    variableId: m.variableId,
  }));
  const marketIds = useMemo(() => new Set(markets.map((m) => m.id)), [markets]);

  const edges = useMemo(
    () =>
      (networkData?.edges ?? [])
        .map((e) => ({ source: e.from, target: e.to }))
        .filter((e) => marketIds.has(e.source) && marketIds.has(e.target)),
    [networkData, marketIds],
  );

  const layout = useMemo(
    () => computeFlowLayout(markets.map((m) => m.id), edges, { orientation: "vertical", columnGap: 40 }),
    [markets, edges],
  );

  const positionById = useMemo(
    () => new Map(layout.nodes.map((n) => [n.id, n])),
    [layout],
  );
  const marketById = useMemo(() => new Map(markets.map((m) => [m.id, m])), [markets]);
  const variableToMarketId = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of markets) if (m.variableId) map.set(m.variableId, m.id);
    return map;
  }, [markets]);

  const assumedByMarketId = useMemo(() => {
    const map = new Map<string, string>();
    for (const a of assumptions) {
      const mid = variableToMarketId.get(a.variableId);
      if (mid) map.set(mid, a.outcomeId);
    }
    return map;
  }, [assumptions, variableToMarketId]);

  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const handleHover = useCallback(
    (info: { id: string; x: number; y: number } | null) => setHover(info),
    [],
  );

  if (isLoading) {
    return (
      <div style={panelStyle}>
        <div style={{ color: "var(--color-text-muted)", textAlign: "center", padding: "var(--space-lg)" }}>
          Loading network…
        </div>
      </div>
    );
  }
  if (markets.length === 0) {
    return (
      <div style={panelStyle}>
        <div style={{ color: "var(--color-text-muted)", textAlign: "center" }}>No markets to visualize.</div>
      </div>
    );
  }

  const evidenceIds = new Set(assumedByMarketId.keys());
  const hoveredMarket = hover ? marketById.get(hover.id) : undefined;
  const hoveredParents = hover
    ? edges.filter((e) => e.target === hover.id).map((e) => marketById.get(e.source)?.title).filter(Boolean)
    : [];

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "var(--space-sm)" }}>
        <h3 style={{ fontSize: "1rem", fontWeight: 600 }}>Belief network</h3>
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          {markets.length} markets · {edges.length} causal links
          {assumptions.length > 0 && ` · conditioned on ${assumptions.length} assumption${assumptions.length > 1 ? "s" : ""}`}
        </span>
      </div>

      <div style={{ position: "relative", overflowX: "auto" }}>
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          style={{ width: "100%", maxWidth: 860, height: "auto", display: "block", margin: "0 auto" }}
          role="img"
          aria-label="Causal belief network of all markets"
        >
          <defs>
            <marker id="bf-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0.8 L 7.2 4 L 0 7.2 Z" fill="var(--color-text-muted)" opacity={0.55} />
            </marker>
            <marker id="bf-arrow-hot" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0.8 L 7.2 4 L 0 7.2 Z" fill="var(--color-info)" />
            </marker>
          </defs>

          {/* Edges: solid hairline beziers, cause above -> effect below */}
          {edges.map((e, i) => {
            const s = positionById.get(e.source);
            const t = positionById.get(e.target);
            if (!s || !t) return null;
            const x1 = s.x + NODE_W / 2;
            const y1 = s.y + NODE_H;
            const x2 = t.x + NODE_W / 2;
            const y2 = t.y - 1.5;
            const my = (y1 + y2) / 2;
            const hot = evidenceIds.has(e.source) || evidenceIds.has(e.target);
            const dimmedByHover = hover != null && hover.id !== e.source && hover.id !== e.target;
            return (
              <path
                key={`${e.source}-${e.target}-${i}`}
                d={`M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`}
                fill="none"
                stroke={hot ? "var(--color-info)" : "var(--color-text-muted)"}
                strokeWidth={hot ? 1.6 : 1}
                opacity={dimmedByHover ? 0.25 : hot ? 1 : 0.5}
                markerEnd={hot ? "url(#bf-arrow-hot)" : "url(#bf-arrow)"}
              />
            );
          })}

          {/* Nodes */}
          {layout.nodes.map((n) => {
            const market = marketById.get(n.id);
            if (!market) return null;
            const context = assumptions
              .filter((a) => a.variableId !== market.variableId)
              .map((a) => ({ variableId: a.variableId, outcomeId: a.outcomeId }));
            return (
              <FlowNode
                key={n.id}
                node={n}
                market={market}
                context={context}
                isFocus={n.id === focusMarketId}
                assumedOutcome={assumedByMarketId.get(n.id)}
                onClick={onNodeClick ? () => onNodeClick(n.id) : undefined}
                onHover={handleHover}
              />
            );
          })}
        </svg>

        {/* Hover tooltip */}
        {hover && hoveredMarket && (
          <div
            style={{
              position: "absolute",
              left: `${((hover.x + NODE_W / 2) / layout.width) * 100}%`,
              top: `${((hover.y + NODE_H + 4) / layout.height) * 100}%`,
              transform: "translateX(-50%)",
              maxWidth: 260,
              padding: "6px 10px",
              borderRadius: 6,
              border: "1px solid var(--color-border)",
              background: "var(--color-bg)",
              fontSize: "0.72rem",
              color: "var(--color-text)",
              pointerEvents: "none",
              zIndex: 5,
              boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 2 }}>{hoveredMarket.title}</div>
            {hoveredParents.length > 0 ? (
              <div style={{ color: "var(--color-text-muted)" }}>
                Depends on: {hoveredParents.join(" · ")}
              </div>
            ) : (
              <div style={{ color: "var(--color-text-muted)" }}>Root driver — no parents</div>
            )}
          </div>
        )}
      </div>

      <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", marginTop: "var(--space-sm)" }}>
        Bars show the probability of Yes on a shared 0–100% scale. Arrows point cause → effect.
        {assumptions.length > 0 && " Deltas (▲▼) are the shift from each market's unconditional price."}
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
