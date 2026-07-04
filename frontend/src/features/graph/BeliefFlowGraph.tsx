import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useMarkets, useMarket, useNetwork } from "@/lib/query/hooks";
import { useOptionalAssumptions } from "@/features/assumptions/AssumptionContext";
import { computeFlowLayout, wrapTitle, DEFAULT_FLOW_OPTIONS, type PositionedNode } from "./flowLayout";
import {
  computeEgoSet,
  induceEdges,
  searchMatchIds,
  firstSearchMatch,
  topMovers,
  firstRootId,
} from "./egoGraph";
import type { MarketSummary } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// The belief-flow view: a layered DAG read left-to-right as cause -> effect.
// One thin bar per node (P of the first outcome, shared 0-100 scale), full
// two-line titles, solid hairline edges with arrowheads, and — when
// assumptions are active — a signed delta against the unconditional prior.
//
// Scale features (built for 1000+ nodes, working at 16): title search with
// fade-out of non-matches, a 2-hop ego "focus mode", and a top-movers strip
// when assumptions are active. Networks past AUTO_FOCUS_NODE_LIMIT nodes
// open focused instead of drawing the full graph.
// ---------------------------------------------------------------------------

const NODE_W = DEFAULT_FLOW_OPTIONS.nodeWidth;
const NODE_H = DEFAULT_FLOW_OPTIONS.nodeHeight;
const BAR_W = NODE_W - 102;
const BAR_H = 5;

/** Above this many nodes the graph defaults to focus mode instead of drawing everything. */
const AUTO_FOCUS_NODE_LIMIT = 40;

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
  dimmed,
  assumedOutcome,
  onClick,
  onFocusRequest,
  onHover,
}: {
  node: PositionedNode;
  market: FlowMarket;
  context: Array<{ variableId: string; outcomeId: string }>;
  isFocus: boolean;
  dimmed: boolean;
  assumedOutcome?: string;
  onClick?: () => void;
  onFocusRequest?: () => void;
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

  const titleLines = wrapTitle(market.title, 32);
  const isResolved = market.status !== "active";

  return (
    <g
      transform={`translate(${node.x}, ${node.y})`}
      data-node-id={market.id}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(); } : undefined}
      onDoubleClick={onFocusRequest ? (e) => { e.stopPropagation(); onFocusRequest(); } : undefined}
      onMouseEnter={() => onHover({ id: market.id, x: node.x, y: node.y })}
      onMouseLeave={() => onHover(null)}
      style={{ cursor: onClick ? "pointer" : "default", opacity: dimmed ? 0.25 : isResolved ? 0.45 : 1 }}
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

/**
 * Renders nothing; subscribes to the same conditioned/base queries as the
 * node and reports the delta upward so the parent can rank top movers
 * without new hooks or extra network traffic (react-query dedupes keys).
 */
function DeltaProbe({
  market,
  context,
  onDelta,
}: {
  market: FlowMarket;
  context: Array<{ variableId: string; outcomeId: string }>;
  onDelta: (id: string, deltaPts: number | null) => void;
}) {
  const conditioned = useMarket(market.id, { context });
  const base = useMarket(market.id);
  const condP = firstOutcomeProbability(conditioned.data?.market);
  const baseP = firstOutcomeProbability(base.data?.market);
  const deltaPts =
    context.length > 0 && condP != null && baseP != null ? (condP.p - baseP.p) * 100 : null;

  const id = market.id;
  useEffect(() => {
    onDelta(id, deltaPts);
  }, [id, deltaPts, onDelta]);
  useEffect(() => () => onDelta(id, null), [id, onDelta]);

  return null;
}

function TopMoversStrip({
  rows,
  onPick,
}: {
  rows: Array<{ id: string; title: string; deltaPts: number }>;
  onPick: (id: string) => void;
}) {
  return (
    <div style={{ width: 180, flexShrink: 0 }}>
      <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", marginBottom: 4 }}>
        Top movers
      </div>
      {rows.map((r) => (
        <button
          key={r.id}
          type="button"
          onClick={() => onPick(r.id)}
          title={r.title}
          style={{
            display: "flex",
            width: "100%",
            alignItems: "baseline",
            gap: 8,
            padding: "2px 0",
            background: "transparent",
            border: "none",
            cursor: "pointer",
            textAlign: "left",
            color: "var(--color-text)",
            fontSize: "0.72rem",
            fontWeight: 600,
          }}
        >
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {r.title}
          </span>
          <span
            style={{
              fontWeight: 700,
              fontVariantNumeric: "tabular-nums",
              color: r.deltaPts > 0 ? "var(--color-success)" : "var(--color-danger)",
            }}
          >
            {r.deltaPts > 0 ? "▲" : "▼"}{Math.abs(r.deltaPts).toFixed(1)}
          </span>
        </button>
      ))}
    </div>
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

  const marketById = useMemo(() => new Map(markets.map((m) => [m.id, m])), [markets]);

  // ---- Focus mode (2-hop ego graph) ----
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const effectiveFocusId = focusedId != null && marketById.has(focusedId) ? focusedId : null;

  // Scale readiness: past the limit, open focused on the biggest mover (or
  // the first root) instead of drawing the whole network. Runs once.
  const [deltaById, setDeltaById] = useState<ReadonlyMap<string, number>>(new Map());
  const autoFocusApplied = useRef(false);
  useEffect(() => {
    if (autoFocusApplied.current) return;
    if (markets.length <= AUTO_FOCUS_NODE_LIMIT) return;
    autoFocusApplied.current = true;
    const ranked = topMovers(
      markets.flatMap((m) => {
        const d = deltaById.get(m.id);
        return d === undefined ? [] : [{ id: m.id, deltaPts: d }];
      }),
      1,
    );
    const target = ranked[0]?.id ?? firstRootId(markets.map((m) => m.id), edges);
    if (target) setFocusedId(target);
  }, [markets, edges, deltaById]);

  const displayed = useMemo(() => {
    const allIds = markets.map((m) => m.id);
    if (!effectiveFocusId) return { ids: allIds, edges };
    const ego = computeEgoSet(effectiveFocusId, edges, 2);
    return { ids: allIds.filter((id) => ego.has(id)), edges: induceEdges(ego, edges) };
  }, [markets, edges, effectiveFocusId]);

  const layout = useMemo(
    () => computeFlowLayout(displayed.ids, displayed.edges, { orientation: "vertical", columnGap: 40 }),
    [displayed],
  );

  const positionById = useMemo(
    () => new Map(layout.nodes.map((n) => [n.id, n])),
    [layout],
  );
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
  const [selected, setSelected] = useState<string | null>(null);

  // ---- Search ----
  const [query, setQuery] = useState("");

  // ---- Top movers ----
  const reportDelta = useCallback((id: string, deltaPts: number | null) => {
    setDeltaById((prev) => {
      const current = prev.get(id);
      if (deltaPts === null ? current === undefined : current === deltaPts) return prev;
      const next = new Map(prev);
      if (deltaPts === null) next.delete(id);
      else next.set(id, deltaPts);
      return next;
    });
  }, []);

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

  const displayedIdSet = new Set(displayed.ids);
  const displayedMarkets = markets.filter((m) => displayedIdSet.has(m.id));
  const matchIds = searchMatchIds(query, displayedMarkets);
  const focusedMarket = effectiveFocusId ? marketById.get(effectiveFocusId) : undefined;

  const contextFor = (market: FlowMarket) =>
    assumptions
      .filter((a) => a.variableId !== market.variableId)
      .map((a) => ({ variableId: a.variableId, outcomeId: a.outcomeId }));

  const moverRows = topMovers(
    markets.flatMap((m) => {
      const d = deltaById.get(m.id);
      return d === undefined ? [] : [{ id: m.id, deltaPts: d }];
    }),
  ).map((v) => ({ ...v, title: marketById.get(v.id)?.title ?? v.id }));

  const handlePickMover = (id: string) => {
    if (effectiveFocusId) setFocusedId(id);
    setSelected(id);
    onNodeClick?.(id);
  };

  const evidenceIds = new Set(assumedByMarketId.keys());
  const hoveredMarket = hover ? marketById.get(hover.id) : undefined;
  const hoveredParents = hover
    ? edges.filter((e) => e.target === hover.id).map((e) => marketById.get(e.source)?.title).filter(Boolean)
    : [];

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "var(--space-sm)", marginBottom: "var(--space-sm)" }}>
        <h3 style={{ fontSize: "1rem", fontWeight: 600 }}>Belief network</h3>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              const id = firstSearchMatch(query, displayedMarkets);
              if (id) {
                setSelected(id);
                onNodeClick?.(id);
              }
            } else if (e.key === "Escape") {
              setQuery("");
            }
          }}
          placeholder="Find event…"
          aria-label="Find event"
          style={searchInputStyle}
        />
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          {markets.length} markets · {edges.length} causal links
          {assumptions.length > 0 && ` · conditioned on ${assumptions.length} assumption${assumptions.length > 1 ? "s" : ""}`}
        </span>
      </div>

      {/* Delta probes feed the top-movers strip and auto-focus (render nothing) */}
      {assumptions.length > 0 &&
        markets.map((m) => (
          <DeltaProbe key={m.id} market={m} context={contextFor(m)} onDelta={reportDelta} />
        ))}

      <div style={{ display: "flex", gap: "var(--space-md)", alignItems: "flex-start" }}>
        <div style={{ position: "relative", overflowX: "auto", flex: 1, minWidth: 0 }}>
          {focusedMarket && (
            <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: 6 }}>
              Focused on <span style={{ color: "var(--color-text)", fontWeight: 600 }}>{focusedMarket.title}</span>
              {" · "}
              <button type="button" onClick={() => setFocusedId(null)} style={linkButtonStyle}>
                Show all {markets.length} events
              </button>
            </div>
          )}

          <svg
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            style={{ width: "100%", maxWidth: 860, height: "auto", display: "block", margin: "0 auto" }}
            role="img"
            aria-label="Causal belief network of all markets"
            onClick={() => setSelected(null)}
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
            {displayed.edges.map((e, i) => {
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
              const dimmedBySearch =
                matchIds != null && !(matchIds.has(e.source) && matchIds.has(e.target));
              return (
                <path
                  key={`${e.source}-${e.target}-${i}`}
                  d={`M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`}
                  fill="none"
                  stroke={hot ? "var(--color-info)" : "var(--color-text-muted)"}
                  strokeWidth={hot ? 1.6 : 1}
                  opacity={dimmedByHover || dimmedBySearch ? 0.25 : hot ? 1 : 0.62}
                  markerEnd={hot ? "url(#bf-arrow-hot)" : "url(#bf-arrow)"}
                />
              );
            })}

            {/* Nodes */}
            {layout.nodes.map((n) => {
              const market = marketById.get(n.id);
              if (!market) return null;
              return (
                <FlowNode
                  key={n.id}
                  node={n}
                  market={market}
                  context={contextFor(market)}
                  isFocus={n.id === focusMarketId || n.id === effectiveFocusId}
                  dimmed={matchIds != null && !matchIds.has(n.id)}
                  assumedOutcome={assumedByMarketId.get(n.id)}
                  onClick={() => {
                    setSelected((prev) => (prev === n.id ? null : n.id));
                    onNodeClick?.(n.id);
                  }}
                  onFocusRequest={() => {
                    setFocusedId(n.id);
                    setSelected(null);
                  }}
                  onHover={handleHover}
                />
              );
            })}
          </svg>

          {/* Pinned popover for the selected node */}
          {selected && positionById.has(selected) && marketById.has(selected) && (
            <NodePopover
              market={marketById.get(selected)!}
              node={positionById.get(selected)!}
              layoutWidth={layout.width}
              layoutHeight={layout.height}
              context={contextFor(marketById.get(selected)!)}
              onFocus={() => setFocusedId(selected)}
              onClose={() => setSelected(null)}
            />
          )}

          {/* Hover tooltip */}
          {hover && hover.id !== selected && hoveredMarket && (
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

        {assumptions.length > 0 && moverRows.length > 0 && (
          <TopMoversStrip rows={moverRows} onPick={handlePickMover} />
        )}
      </div>

      <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", marginTop: "var(--space-sm)" }}>
        Bars show the probability of Yes on a shared 0–100% scale. Arrows point cause → effect.
        {assumptions.length > 0 && " Deltas (▲▼) are the shift from each market's unconditional price."}
      </div>
    </div>
  );
}

function NodePopover({
  market,
  node,
  layoutWidth,
  layoutHeight,
  context,
  onFocus,
  onClose,
}: {
  market: FlowMarket;
  node: PositionedNode;
  layoutWidth: number;
  layoutHeight: number;
  context: Array<{ variableId: string; outcomeId: string }>;
  onFocus: () => void;
  onClose: () => void;
}) {
  const conditioned = useMarket(market.id, { context });
  const base = useMarket(market.id);
  const assumptionState = useOptionalAssumptions();

  const detail = conditioned.data?.market ?? base.data?.market;
  const condP = firstOutcomeProbability(conditioned.data?.market);
  const baseP = firstOutcomeProbability(base.data?.market);
  const shown = condP ?? baseP;
  const deltaPts = context.length > 0 && condP && baseP ? (condP.p - baseP.p) * 100 : 0;
  const assumed = market.variableId ? assumptionState?.getAssumption(market.variableId) : undefined;

  const leftPct = Math.min(88, Math.max(12, ((node.x + 96) / layoutWidth) * 100));

  return (
    <div
      style={{
        position: "absolute",
        left: `${leftPct}%`,
        top: `${((node.y + 66) / layoutHeight) * 100}%`,
        transform: "translateX(-50%)",
        width: 300,
        padding: "10px 12px",
        borderRadius: 8,
        border: "1px solid var(--color-primary)",
        background: "var(--color-bg)",
        fontSize: "0.75rem",
        color: "var(--color-text)",
        zIndex: 6,
        boxShadow: "0 6px 20px rgba(0,0,0,0.5)",
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <div style={{ fontWeight: 700, lineHeight: 1.3 }}>{market.title}</div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          style={{ background: "transparent", border: "none", color: "var(--color-text-muted)", cursor: "pointer", fontSize: "0.9rem", lineHeight: 1 }}
        >
          ×
        </button>
      </div>

      {detail?.description && (
        <div style={{ color: "var(--color-text-muted)", margin: "6px 0", lineHeight: 1.4 }}>
          {detail.description}
        </div>
      )}

      {shown && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "6px 0" }}>
          <span style={{ fontSize: "1.15rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
            {(shown.p * 100).toFixed(1)}%
          </span>
          <span style={{ color: "var(--color-text-muted)" }}>P(yes{context.length > 0 ? " | assumptions" : ""})</span>
          {Math.abs(deltaPts) >= 0.05 && (
            <span
              style={{
                fontWeight: 700,
                fontVariantNumeric: "tabular-nums",
                color: deltaPts > 0 ? "var(--color-success)" : "var(--color-danger)",
              }}
            >
              {deltaPts > 0 ? "▲" : "▼"}{Math.abs(deltaPts).toFixed(1)}
            </span>
          )}
        </div>
      )}

      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
        {assumptionState && market.variableId && market.status === "active" &&
          (detail?.outcomes ?? []).slice(0, 3).map((o) => {
            const isThis = assumed?.outcomeId === o.id;
            return (
              <button
                key={o.id}
                type="button"
                onClick={() => {
                  if (isThis) {
                    assumptionState.removeAssumption(market.variableId!);
                  } else {
                    assumptionState.addAssumption({
                      variableId: market.variableId!,
                      outcomeId: o.id,
                      label: market.title,
                    });
                  }
                }}
                style={{
                  padding: "3px 10px",
                  borderRadius: 4,
                  fontSize: "0.7rem",
                  fontWeight: 600,
                  cursor: "pointer",
                  border: `1px solid ${isThis ? "var(--color-primary)" : "var(--color-border)"}`,
                  background: isThis ? "var(--color-primary)" : "transparent",
                  color: isThis ? "#fff" : "var(--color-text)",
                }}
              >
                {isThis ? `✓ Assumed ${o.name}` : `Assume ${o.name}`}
              </button>
            );
          })}
        <button
          type="button"
          onClick={onFocus}
          style={{
            marginLeft: "auto",
            alignSelf: "center",
            fontSize: "0.7rem",
            fontWeight: 600,
            color: "var(--color-primary)",
            background: "transparent",
            border: "none",
            padding: 0,
            cursor: "pointer",
          }}
        >
          Focus
        </button>
        <Link
          to={`/markets/${market.id}`}
          style={{
            alignSelf: "center",
            fontSize: "0.7rem",
            fontWeight: 600,
            color: "var(--color-primary)",
            textDecoration: "none",
          }}
        >
          Open market →
        </Link>
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

const searchInputStyle: React.CSSProperties = {
  marginLeft: "auto",
  width: 150,
  padding: "2px 8px",
  fontSize: "0.72rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
};

const linkButtonStyle: React.CSSProperties = {
  background: "transparent",
  border: "none",
  padding: 0,
  fontSize: "inherit",
  fontWeight: 600,
  color: "var(--color-primary)",
  cursor: "pointer",
};
