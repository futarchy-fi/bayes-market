import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useMarkets, useMarket, useNetwork, useGraphMarkets } from "@/lib/query/hooks";
import { useOptionalAssumptions } from "@/features/assumptions/AssumptionContext";
import { FormattedDescription } from "@/components/ui/FormattedDescription";
import { computeFlowLayout, wrapTitle, DEFAULT_FLOW_OPTIONS, type PositionedNode } from "./flowLayout";
import {
  computeEgoSet,
  induceEdges,
  searchMatchIds,
  topMovers,
  firstRootId,
} from "./egoGraph";
import { isContextContradictedError } from "./mapLayout";
import type { GraphMarket, MarketSummary } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// The belief-flow view: a layered DAG read top-to-bottom as cause -> effect.
// All probabilities and assumption deltas come from the single bulk
// useMarkets() + useGraphMarkets(context) responses — zero per-node queries
// and zero <DeltaProbe> request storms.
// ---------------------------------------------------------------------------

const NODE_W = DEFAULT_FLOW_OPTIONS.nodeWidth;
const NODE_H = DEFAULT_FLOW_OPTIONS.nodeHeight;
const BAR_W = NODE_W - 102;
const BAR_H = 5;

/** Above this many nodes the graph opens in ego-focus mode. */
const AUTO_FOCUS_NODE_LIMIT = 40;

/** Hard ceiling on rendered FlowNode SVG groups to keep layout snappy. */
const MAX_RENDERED_NODES = 60;

/** Maximum search results rendered inside the Find event dropdown. */
const MAX_SEARCH_DROPDOWN = 12;

interface BeliefFlowGraphProps {
  focusMarketId?: string;
  onNodeClick?: (marketId: string) => void;
}

interface FlowMarket {
  id: string;
  title: string;
  status: string;
  variableId?: string;
  marginals?: Record<string, number>;
  outcomes?: Array<{ id: string; name: string }>;
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

function computeAutoFocusTarget(
  markets: FlowMarket[],
  edges: Array<{ source: string; target: string }>,
  deltaById: ReadonlyMap<string, number>,
): string | null {
  const ranked = topMovers(
    markets.flatMap((m) => {
      const d = deltaById.get(m.id);
      return d === undefined ? [] : [{ id: m.id, deltaPts: d }];
    }),
    1,
  );
  return ranked[0]?.id ?? firstRootId(markets.map((m) => m.id), edges);
}

function primaryProbabilityFromRecord(
  marginals: Record<string, number> | undefined,
  outcomes?: Array<{ id: string }>,
): number | null {
  if (!marginals) return null;
  if (typeof marginals.yes === "number") return marginals.yes;
  const firstOutcomeId = outcomes?.[0]?.id;
  if (firstOutcomeId && typeof marginals[firstOutcomeId] === "number") {
    return marginals[firstOutcomeId]!;
  }
  const firstVal = Object.values(marginals)[0];
  return typeof firstVal === "number" ? firstVal : null;
}

function FlowNode({
  node,
  market,
  baseP,
  condP,
  hasAssumptions,
  isFocus,
  dimmed,
  assumedOutcome,
  onClick,
  onFocusRequest,
  onHover,
}: {
  node: PositionedNode;
  market: FlowMarket;
  baseP: number | null;
  condP: number | null;
  hasAssumptions: boolean;
  isFocus: boolean;
  dimmed: boolean;
  assumedOutcome?: string;
  onClick?: () => void;
  onFocusRequest?: () => void;
  onHover: (info: { id: string; x: number; y: number } | null) => void;
}) {
  const shown = hasAssumptions && condP != null ? condP : baseP;
  const hasDelta = hasAssumptions && !assumedOutcome && condP != null && baseP != null;
  const deltaPts = hasDelta ? (condP - baseP) * 100 : 0;
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
      style={{
        cursor: onClick ? "pointer" : "default",
        opacity: dimmed ? 0.25 : isResolved ? 0.45 : 1,
        userSelect: "none",
      }}
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
          style={{ userSelect: "none" }}
        >
          {line}
        </text>
      ))}

      {/* Single probability bar: track + fill on a shared 0-100 scale */}
      <rect x={10} y={NODE_H - 19} width={BAR_W} height={BAR_H} rx={BAR_H / 2} fill="var(--color-border)" />
      {shown != null && shown > 0.004 && (
        <path
          d={barPath(10, NODE_H - 19, Math.max(2, shown * BAR_W), BAR_H)}
          fill="var(--color-info)"
        />
      )}
      {shown != null && (
        <text
          x={10 + BAR_W + 7}
          y={NODE_H - 13.5}
          fontSize="10.5"
          fontWeight={600}
          fill="var(--color-text)"
          style={{ fontVariantNumeric: "tabular-nums", userSelect: "none" }}
        >
          {(shown * 100).toFixed(1)}%
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
          style={{ fontVariantNumeric: "tabular-nums", userSelect: "none" }}
        >
          {deltaPts > 0 ? "▲" : "▼"}{Math.abs(deltaPts).toFixed(1)}
        </text>
      )}

      {/* Evidence badge for assumed variables */}
      {assumedOutcome && (
        <g transform={`translate(10, ${NODE_H - 10})`}>
          <rect width={62} height={11} rx={3} fill="var(--color-primary)" />
          <text
            x={31}
            y={8.5}
            textAnchor="middle"
            fontSize="7.5"
            fontWeight={700}
            fill="#fff"
            style={{ userSelect: "none" }}
          >
            GIVEN: {assumedOutcome.toUpperCase()}
          </text>
        </g>
      )}
    </g>
  );
}

function TopMoversStrip({
  rows,
  onPick,
}: {
  rows: Array<{ id: string; title: string; deltaPts: number }>;
  onPick: (id: string) => void;
}) {
  return (
    <div style={{ width: 190, flexShrink: 0 }}>
      <div style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", marginBottom: 4, fontWeight: 600 }}>
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
            padding: "3px 0",
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
  const contextPayload = useMemo(
    () => assumptions.map((a) => ({ variableId: a.variableId, outcomeId: a.outcomeId })),
    [assumptions],
  );
  const hasAssumptions = contextPayload.length > 0;

  // Single bulk conditioned query instead of N+1 <DeltaProbe> / <FlowNode> queries.
  const conditionedGraph = useGraphMarkets(contextPayload, { enabled: hasAssumptions });
  const lastGoodGraphRef = useRef<GraphMarket[] | undefined>(undefined);
  if (conditionedGraph?.data?.markets) {
    lastGoodGraphRef.current = conditionedGraph.data.markets;
  }
  const graphMarkets = conditionedGraph?.data?.markets ?? (hasAssumptions ? lastGoodGraphRef.current : undefined) ?? [];
  const graphById = useMemo(() => new Map(graphMarkets.map((gm) => [gm.id, gm])), [graphMarkets]);
  const contradicted = hasAssumptions && isContextContradictedError(conditionedGraph?.error);

  const markets: FlowMarket[] = useMemo(
    () =>
      (marketsData?.markets ?? []).map((m: MarketSummary) => ({
        id: m.id,
        title: m.title,
        status: m.status,
        variableId: m.variableId,
        marginals: m.marginals,
        outcomes: m.outcomes,
      })),
    [marketsData],
  );
  const marketIds = useMemo(() => new Set(markets.map((m) => m.id)), [markets]);
  const marketById = useMemo(() => new Map(markets.map((m) => [m.id, m])), [markets]);

  const edges = useMemo(
    () =>
      (networkData?.edges ?? [])
        .map((e) => ({ source: e.from, target: e.to }))
        .filter((e) => marketIds.has(e.source) && marketIds.has(e.target)),
    [networkData, marketIds],
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

  // Compute unconditional base probabilities, conditioned probabilities, and deltas synchronously.
  const { baseProbById, condProbById, deltaById } = useMemo(() => {
    const baseMap = new Map<string, number>();
    const condMap = new Map<string, number>();
    const deltas = new Map<string, number>();
    for (const m of markets) {
      const gm = graphById.get(m.id);
      const baseP =
        primaryProbabilityFromRecord(gm?.marginals as Record<string, number> | undefined, m.outcomes) ??
        primaryProbabilityFromRecord(m.marginals, m.outcomes);
      if (baseP != null) baseMap.set(m.id, baseP);

      const condP = hasAssumptions
        ? primaryProbabilityFromRecord(gm?.conditionalMarginals as Record<string, number> | undefined, m.outcomes)
        : null;
      if (condP != null) {
        condMap.set(m.id, condP);
        if (baseP != null && !assumedByMarketId.has(m.id)) {
          deltas.set(m.id, (condP - baseP) * 100);
        }
      }
    }
    return { baseProbById: baseMap, condProbById: condMap, deltaById: deltas };
  }, [markets, graphById, hasAssumptions, assumedByMarketId]);

  // ---- Focus & scope state ----
  // userFocusedId overrides focusMarketId when the user double-clicks or picks from search.
  const [userFocusedId, setUserFocusedId] = useState<string | null>(null);
  const [hopDepth, setHopDepth] = useState<1 | 2>(2);
  const [showAllSmall, setShowAllSmall] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  // When navigating to a different /markets/:id, immediately snap focus to the new market.
  useEffect(() => {
    setUserFocusedId(null);
    setHopDepth(2);
    setSelected(null);
  }, [focusMarketId]);

  const isLargeNetwork = markets.length > AUTO_FOCUS_NODE_LIMIT;

  const autoFocusId = useMemo(
    () => (isLargeNetwork ? computeAutoFocusTarget(markets, edges, deltaById) : null),
    [isLargeNetwork, markets, edges, deltaById],
  );

  const validUserFocus = userFocusedId != null && marketById.has(userFocusedId) ? userFocusedId : null;
  const validPropFocus = focusMarketId != null && marketById.has(focusMarketId) ? focusMarketId : null;

  // On large networks (>40), always stay focused (user selection -> prop focusMarketId -> auto).
  // On small networks (<=40), default to showing all unless user chooses 1-hop/2-hop or focuses a node.
  const effectiveFocusId = isLargeNetwork
    ? (validUserFocus ?? validPropFocus ?? autoFocusId)
    : (validUserFocus ?? (!showAllSmall ? validPropFocus : null));

  const displayed = useMemo(() => {
    const allIds = markets.map((m) => m.id);
    if (!effectiveFocusId) return { ids: allIds, edges };
    const ego = computeEgoSet(effectiveFocusId, edges, hopDepth);
    return { ids: allIds.filter((id) => ego.has(id)), edges: induceEdges(ego, edges) };
  }, [markets, edges, effectiveFocusId, hopDepth]);

  // Hard cap: never render more than MAX_RENDERED_NODES FlowNode groups.
  const renderedIds = useMemo(() => {
    if (displayed.ids.length <= MAX_RENDERED_NODES) return displayed.ids;
    if (effectiveFocusId && displayed.ids.includes(effectiveFocusId)) {
      const rest = displayed.ids.filter((id) => id !== effectiveFocusId);
      return [effectiveFocusId, ...rest.slice(0, MAX_RENDERED_NODES - 1)];
    }
    return displayed.ids.slice(0, MAX_RENDERED_NODES);
  }, [displayed.ids, effectiveFocusId]);
  const renderedIdSet = useMemo(() => new Set(renderedIds), [renderedIds]);
  const truncatedCount = displayed.ids.length - renderedIds.length;
  const renderedEdges = useMemo(
    () => (truncatedCount > 0 ? induceEdges(renderedIdSet, displayed.edges) : displayed.edges),
    [displayed.edges, renderedIdSet, truncatedCount],
  );

  const layout = useMemo(
    () => computeFlowLayout(renderedIds, renderedEdges, { orientation: "vertical", columnGap: 40 }),
    [renderedIds, renderedEdges],
  );

  const positionById = useMemo(
    () => new Map(layout.nodes.map((n) => [n.id, n])),
    [layout],
  );

  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const handleHover = useCallback(
    (info: { id: string; x: number; y: number } | null) => setHover(info),
    [],
  );

  // ---- Search across ALL markets ----
  const [query, setQuery] = useState("");
  const [searchFocused, setSearchFocused] = useState(false);

  const allSearchMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return markets.filter(
      (m) =>
        m.title.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        (m.variableId?.toLowerCase().includes(q) ?? false),
    );
  }, [query, markets]);

  const refocusOnMarket = useCallback((id: string) => {
    setUserFocusedId(id);
    setShowAllSmall(false);
    setSelected(null);
    setQuery("");
    setSearchFocused(false);
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

  const renderedMarkets = markets.filter((m) => renderedIdSet.has(m.id));
  const matchIds = searchMatchIds(query, renderedMarkets);
  const focusedMarket = effectiveFocusId ? marketById.get(effectiveFocusId) : undefined;

  const moverRows = topMovers(
    markets.flatMap((m) => {
      const d = deltaById.get(m.id);
      return d === undefined ? [] : [{ id: m.id, deltaPts: d }];
    }),
  ).map((v) => ({ ...v, title: marketById.get(v.id)?.title ?? v.id }));

  const handlePickMover = (id: string) => {
    setUserFocusedId(id);
    setShowAllSmall(false);
    setSelected(id);
    onNodeClick?.(id);
  };

  const evidenceIds = new Set(assumedByMarketId.keys());
  const hoveredMarket = hover ? marketById.get(hover.id) : undefined;
  const hoveredParents = hover
    ? edges.filter((e) => e.target === hover.id).map((e) => marketById.get(e.source)?.title).filter(Boolean)
    : [];

  const isOnPropFocusDefault =
    validPropFocus != null && effectiveFocusId === validPropFocus && hopDepth === 2 && !showAllSmall;
  const lastAssumption = assumptions[assumptions.length - 1];

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: "var(--space-sm)", marginBottom: "var(--space-sm)" }}>
        <h3 style={{ fontSize: "1rem", fontWeight: 600 }}>Belief network</h3>
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          {markets.length} markets · {edges.length} causal links
          {hasAssumptions && ` · conditioned on ${assumptions.length} assumption${assumptions.length > 1 ? "s" : ""}`}
        </span>

        {/* Search across ALL markets with clickable dropdown */}
        <div style={{ position: "relative", marginLeft: "auto" }}>
          <input
            type="text"
            value={query}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setTimeout(() => setSearchFocused(false), 150)}
            onChange={(e) => {
              setQuery(e.target.value);
              setSearchFocused(true);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const first = allSearchMatches[0];
                if (first) {
                  refocusOnMarket(first.id);
                  onNodeClick?.(first.id);
                }
              } else if (e.key === "Escape") {
                setQuery("");
                setSearchFocused(false);
              }
            }}
            placeholder="Find event…"
            aria-label="Find event"
            style={searchInputStyle}
          />

          {searchFocused && query.trim().length > 0 && (
            <div role="listbox" aria-label="Matching events" style={searchDropdownStyle}>
              <div style={{ padding: "4px 8px", fontSize: "0.68rem", color: "var(--color-text-muted)", borderBottom: "1px solid var(--color-border)" }}>
                {allSearchMatches.length === 0
                  ? "No matching markets"
                  : `${allSearchMatches.length} match${allSearchMatches.length === 1 ? "" : "es"} across all markets`}
              </div>
              {allSearchMatches.slice(0, MAX_SEARCH_DROPDOWN).map((m) => {
                const p = (hasAssumptions ? condProbById.get(m.id) : undefined) ?? baseProbById.get(m.id);
                return (
                  <button
                    key={m.id}
                    type="button"
                    role="option"
                    aria-selected={m.id === effectiveFocusId}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      refocusOnMarket(m.id);
                      onNodeClick?.(m.id);
                    }}
                    style={searchOptionStyle}
                  >
                    <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {m.title}
                    </span>
                    {p != null && (
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--color-info)", flexShrink: 0 }}>
                        {(p * 100).toFixed(1)}%
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {contradicted && (
        <div role="alert" style={contradictionBannerStyle}>
          <span>
            Contradictory assumption: those outcomes have zero joint probability in the network. Remove an assumption or Clear all.
          </span>
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            {assumptionState && lastAssumption && (
              <button
                type="button"
                onClick={() => assumptionState.removeAssumption(lastAssumption.variableId)}
                style={bannerBtnStyle}
              >
                Undo last
              </button>
            )}
            {assumptionState && (
              <button type="button" onClick={assumptionState.clearAll} style={bannerBtnStyle}>
                Clear all
              </button>
            )}
          </div>
        </div>
      )}

      {/* Scope & focus controls */}
      {(focusedMarket || validPropFocus) && (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: 8 }}>
          {focusedMarket ? (
            <span>
              Focused on <span style={{ color: "var(--color-text)", fontWeight: 600 }}>{focusedMarket.title}</span>
              {" "}({renderedIds.length} node{renderedIds.length !== 1 ? "s" : ""})
            </span>
          ) : (
            <span>Showing all {markets.length} events</span>
          )}
          <div style={{ display: "inline-flex", gap: 4, marginLeft: "auto", flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => {
                setHopDepth(1);
                setShowAllSmall(false);
                if (!effectiveFocusId && validPropFocus) setUserFocusedId(validPropFocus);
              }}
              style={effectiveFocusId && hopDepth === 1 ? scopeBtnActiveStyle : scopeBtnStyle}
            >
              1-hop
            </button>
            <button
              type="button"
              onClick={() => {
                setHopDepth(2);
                setShowAllSmall(false);
                if (!effectiveFocusId && validPropFocus) setUserFocusedId(validPropFocus);
              }}
              style={effectiveFocusId && hopDepth === 2 ? scopeBtnActiveStyle : scopeBtnStyle}
            >
              2-hop
            </button>
            {!isLargeNetwork && (
              <button
                type="button"
                onClick={() => {
                  setUserFocusedId(null);
                  setShowAllSmall(true);
                }}
                style={!effectiveFocusId ? scopeBtnActiveStyle : scopeBtnStyle}
              >
                All ({markets.length})
              </button>
            )}
            {validPropFocus && (
              <button
                type="button"
                disabled={isLargeNetwork ? isOnPropFocusDefault : effectiveFocusId === validPropFocus && hopDepth === 2}
                onClick={() => {
                  setUserFocusedId(null);
                  setHopDepth(2);
                  setShowAllSmall(false);
                  setSelected(null);
                  setQuery("");
                }}
                style={{
                  ...scopeBtnStyle,
                  opacity: (isLargeNetwork ? isOnPropFocusDefault : effectiveFocusId === validPropFocus && hopDepth === 2) ? 0.5 : 1,
                  cursor: (isLargeNetwork ? isOnPropFocusDefault : effectiveFocusId === validPropFocus && hopDepth === 2) ? "default" : "pointer",
                }}
              >
                Reset to this market
              </button>
            )}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: "var(--space-md)", alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ position: "relative", overflowX: "auto", flex: 1, minWidth: 0 }}>
          {truncatedCount > 0 && (
            <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)", marginBottom: 6 }}>
              Showing {MAX_RENDERED_NODES} of {displayed.ids.length} — use search or 1-hop focus.
            </div>
          )}

          <svg
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            style={{ width: "100%", maxWidth: 860, height: "auto", display: "block", margin: "0 auto", userSelect: "none", WebkitUserSelect: "none" }}
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
            {renderedEdges.map((e, i) => {
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
                  baseP={baseProbById.get(n.id) ?? null}
                  condP={condProbById.get(n.id) ?? null}
                  hasAssumptions={hasAssumptions}
                  isFocus={n.id === effectiveFocusId || (!effectiveFocusId && n.id === focusMarketId)}
                  dimmed={matchIds != null && !matchIds.has(n.id)}
                  assumedOutcome={assumedByMarketId.get(n.id)}
                  onClick={() => {
                    setSelected((prev) => (prev === n.id ? null : n.id));
                    onNodeClick?.(n.id);
                  }}
                  onFocusRequest={() => {
                    setUserFocusedId(n.id);
                    setShowAllSmall(false);
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
              baseP={baseProbById.get(selected) ?? null}
              condP={condProbById.get(selected) ?? null}
              hasAssumptions={hasAssumptions}
              onFocus={() => {
                setUserFocusedId(selected);
                setShowAllSmall(false);
                setSelected(null);
              }}
              onClose={() => setSelected(null)}
            />
          )}

          {/* Hover tooltip */}
          {hover && hover.id !== selected && hoveredMarket && (
            <div
              style={{
                position: "absolute",
                left: `${Math.min(82, Math.max(18, ((hover.x + NODE_W / 2) / layout.width) * 100))}%`,
                top: `${Math.min(84, ((hover.y + NODE_H + 4) / layout.height) * 100)}%`,
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

        {hasAssumptions && moverRows.length > 0 && (
          <TopMoversStrip rows={moverRows} onPick={handlePickMover} />
        )}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 6, fontSize: "0.72rem", color: "var(--color-text-muted)", marginTop: "var(--space-sm)" }}>
        <span>
          Bars show P(yes) on a 0–100% scale. Arrows point cause → effect.
          {hasAssumptions && " Deltas (▲▼) show shift from the unconditional prior."}
        </span>
        <span>Click to inspect · Double-click to refocus</span>
      </div>
    </div>
  );
}

function NodePopover({
  market,
  node,
  layoutWidth,
  layoutHeight,
  baseP,
  condP,
  hasAssumptions,
  onFocus,
  onClose,
}: {
  market: FlowMarket;
  node: PositionedNode;
  layoutWidth: number;
  layoutHeight: number;
  baseP: number | null;
  condP: number | null;
  hasAssumptions: boolean;
  onFocus: () => void;
  onClose: () => void;
}) {
  // Fetch full details (description/outcomes) only for the single inspected node.
  const detailQuery = useMarket(market.id);
  const assumptionState = useOptionalAssumptions();

  const detail = detailQuery.data?.market;
  const shown = hasAssumptions && condP != null ? condP : (baseP ?? primaryProbabilityFromRecord(detail?.marginals, detail?.outcomes));
  const deltaPts = hasAssumptions && condP != null && baseP != null ? (condP - baseP) * 100 : 0;
  const assumed = market.variableId ? assumptionState?.getAssumption(market.variableId) : undefined;
  const outcomes = detail?.outcomes ?? market.outcomes ?? [
    { id: "yes", name: "Yes" },
    { id: "no", name: "No" },
  ];

  const isCertainYes = shown != null && shown >= 0.9995;
  const isCertainNo = shown != null && shown <= 0.0005;
  const leftPct = Math.min(82, Math.max(18, ((node.x + NODE_W / 2) / layoutWidth) * 100));

  return (
    <div
      style={{
        position: "absolute",
        left: `${leftPct}%`,
        top: `${Math.min(80, ((node.y + NODE_H - 6) / layoutHeight) * 100)}%`,
        transform: "translateX(-50%)",
        width: 300,
        maxWidth: "calc(100% - 16px)",
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
        <div style={{ color: "var(--color-text-muted)", margin: "6px 0", lineHeight: 1.4, maxHeight: 72, overflowY: "auto" }}>
          <FormattedDescription text={detail.description} />
        </div>
      )}

      {shown != null && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "6px 0", flexWrap: "wrap" }}>
          <span style={{ fontSize: "1.1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
            {(shown * 100).toFixed(1)}%
          </span>
          <span style={{ color: "var(--color-text-muted)" }}>
            P(yes{hasAssumptions ? " | assumptions" : ""})
          </span>
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

      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {assumptionState && market.variableId && market.status === "active" &&
          outcomes.slice(0, 3).map((o) => {
            const isThis = assumed?.outcomeId === o.id;
            const disabled = !isThis && ((o.id === "no" && isCertainYes) || (o.id === "yes" && isCertainNo));
            return (
              <button
                key={o.id}
                type="button"
                disabled={disabled}
                title={disabled ? "Certain under current assumptions" : undefined}
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
                  cursor: disabled ? "not-allowed" : "pointer",
                  opacity: disabled ? 0.45 : 1,
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
      {!assumed && (isCertainYes || isCertainNo) && (
        <div style={{ marginTop: 4, fontSize: "0.68rem", color: "var(--color-text-muted)" }}>
          Certain under current assumptions
        </div>
      )}
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

const searchInputStyle: React.CSSProperties = {
  width: 190,
  padding: "4px 8px",
  fontSize: "0.75rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
};

const searchDropdownStyle: React.CSSProperties = {
  position: "absolute",
  top: "calc(100% + 4px)",
  right: 0,
  width: 280,
  maxWidth: "85vw",
  maxHeight: 260,
  overflowY: "auto",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
  zIndex: 10,
};

const searchOptionStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
  padding: "6px 8px",
  border: "none",
  borderBottom: "1px solid var(--color-border)",
  background: "transparent",
  color: "var(--color-text)",
  fontSize: "0.72rem",
  textAlign: "left",
  cursor: "pointer",
};

const scopeBtnStyle: React.CSSProperties = {
  padding: "2px 8px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text-muted)",
  fontSize: "0.7rem",
  fontWeight: 500,
  cursor: "pointer",
};

const scopeBtnActiveStyle: React.CSSProperties = {
  ...scopeBtnStyle,
  border: "1px solid var(--color-primary)",
  background: "var(--color-primary)",
  color: "#fff",
  fontWeight: 600,
};

const contradictionBannerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  flexWrap: "wrap",
  gap: 8,
  padding: "8px 12px",
  marginBottom: "var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-warning)",
  background: "rgba(234, 179, 8, 0.12)",
  color: "var(--color-text)",
  fontSize: "0.78rem",
};

const bannerBtnStyle: React.CSSProperties = {
  padding: "3px 8px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.72rem",
  fontWeight: 600,
  cursor: "pointer",
};
