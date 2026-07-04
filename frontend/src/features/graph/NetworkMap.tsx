import { useMemo, useState, useCallback, type MouseEvent } from "react";
import { Link } from "react-router-dom";
import { useGraphMarkets } from "@/lib/query/hooks";
import { useOptionalAssumptions } from "@/features/assumptions/AssumptionContext";
import type { GraphMarket } from "@/lib/api/types";
import {
  computeMapLayout,
  edgeBezierPath,
  colorForGroup,
  deltaToColor,
  sourceTag,
  searchMatchIds,
  type PositionedMapNode,
  type MapLayout,
} from "./mapLayout";

// ---------------------------------------------------------------------------
// The landing hero: every market (~900) and every CPT edge (~1000-1500) on
// one structured timeline map -- X = resolution year, Y = fixed family
// bands. All data comes from the single bulk useGraphMarkets response; no
// per-node queries. Hover highlights adjacency (precomputed in mapLayout),
// click opens a popover wired to the shared AssumptionContext, and an
// "assumption mode" recolors nodes by delta once any assumption is active.
// ---------------------------------------------------------------------------

const NODE_R = 3.5;
const HIT_R = 7;

function displayProbability(market: GraphMarket): number | null {
  const p = market.conditionalMarginals?.yes ?? market.marginals?.yes;
  return typeof p === "number" ? p : null;
}

function deltaOf(market: GraphMarket): number | null {
  if (!market.conditionalMarginals) return null;
  const base = market.marginals?.yes;
  const cond = market.conditionalMarginals.yes;
  if (typeof base !== "number" || typeof cond !== "number") return null;
  return cond - base;
}

export function NetworkMap() {
  const assumptionState = useOptionalAssumptions();
  const context = assumptionState?.contextPayload ?? [];
  const assumptionMode = context.length > 0;

  const { data, isLoading } = useGraphMarkets(context);
  const markets = useMemo(() => data?.markets ?? [], [data]);

  const marketById = useMemo(() => new Map(markets.map((m) => [m.id, m])), [markets]);

  const layout: MapLayout = useMemo(
    () =>
      computeMapLayout(
        markets.map((m) => ({
          id: m.id,
          variableId: m.variableId,
          title: m.title,
          status: m.status,
          parents: m.parents,
        })),
      ),
    [markets],
  );

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const neighborSet = hoveredId ? layout.neighborsOf.get(hoveredId) ?? new Set<string>() : null;
  const matchIds = searchMatchIds(query, markets);

  const isDimmed = useCallback(
    (id: string) => {
      const dimmedByHover = hoveredId != null && id !== hoveredId && !neighborSet?.has(id);
      const dimmedBySearch = matchIds != null && !matchIds.has(id);
      return dimmedByHover || dimmedBySearch;
    },
    [hoveredId, neighborSet, matchIds],
  );

  const isHighlighted = useCallback(
    (id: string) => hoveredId != null && (id === hoveredId || (neighborSet?.has(id) ?? false)),
    [hoveredId, neighborSet],
  );

  const colorFor = useCallback(
    (node: PositionedMapNode): string => {
      const market = marketById.get(node.id);
      if (assumptionMode && market) {
        const delta = deltaOf(market);
        if (delta != null) return deltaToColor(delta);
      }
      return colorForGroup(node.group);
    },
    [assumptionMode, marketById],
  );

  const assumedVariableIds = useMemo(
    () => new Set((assumptionState?.assumptions ?? []).map((a) => a.variableId)),
    [assumptionState?.assumptions],
  );
  const isAssumed = useCallback(
    (id: string) => {
      const v = marketById.get(id)?.variableId;
      return v != null && assumedVariableIds.has(v);
    },
    [marketById, assumedVariableIds],
  );

  const positionById = useMemo(() => new Map(layout.nodes.map((n) => [n.id, n])), [layout]);

  // Event delegation: two handlers total regardless of node count.
  const handleMouseOver = useCallback((e: MouseEvent<SVGGElement>) => {
    const id = (e.target as SVGElement).getAttribute("data-node-id");
    if (id) setHoveredId(id);
  }, []);
  const handleMouseOut = useCallback(() => setHoveredId(null), []);
  const handleClick = useCallback((e: MouseEvent<SVGSVGElement>) => {
    const id = (e.target as SVGElement).getAttribute?.("data-node-id");
    setSelectedId(id ?? null);
  }, []);

  const yearTicks = useMemo(() => {
    const ticks: number[] = [];
    for (let y = layout.yearMin; y <= layout.yearMax; y++) ticks.push(y);
    return ticks;
  }, [layout.yearMin, layout.yearMax]);

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

  const selectedMarket = selectedId ? marketById.get(selectedId) : undefined;
  const selectedNode = selectedId ? positionById.get(selectedId) : undefined;
  const hoveredMarket = hoveredId && hoveredId !== selectedId ? marketById.get(hoveredId) : undefined;
  const hoveredNode = hoveredMarket ? positionById.get(hoveredMarket.id) : undefined;

  return (
    <div style={panelStyle}>
      <div style={toolbarStyle}>
        <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>
          {markets.length.toLocaleString()} markets · {layout.edges.length.toLocaleString()} links
        </span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search markets…"
          aria-label="Search markets"
          style={searchInputStyle}
        />
      </div>

      {assumptionMode && (
        <div style={legendRowStyle}>
          <LegendChip color="#d75928" label="Fell under your assumptions" />
          <LegendChip color="#6b7280" label="No meaningful change" />
          <LegendChip color="#0095d7" label="Rose under your assumptions" />
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", border: "2px solid var(--color-primary)", display: "inline-block" }} />
            Assumed
          </span>
        </div>
      )}

      <div style={{ position: "relative", overflowX: "auto" }}>
        <svg
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          style={{ width: "100%", minWidth: 960, height: "auto", display: "block" }}
          role="img"
          aria-label="Full belief network of all markets"
          onClick={handleClick}
        >
          {/* Year gridlines + labels */}
          {yearTicks.map((year) => {
            const x = layout.yearToX(year);
            return (
              <g key={year}>
                <line
                  x1={x}
                  y1={4}
                  x2={x}
                  y2={layout.height - 4}
                  stroke="var(--color-border)"
                  strokeWidth={1}
                  opacity={0.35}
                />
                <text x={x} y={14} fontSize="8.5" fill="var(--color-text-muted)" textAnchor="middle">
                  {year}
                </text>
              </g>
            );
          })}
          {[
            { x: layout.yearToX(2026), label: "≤2026" },
            { x: layout.yearToX(2046), label: "2046+" },
            { x: layout.yearToX(null), label: "Undated" },
          ].map(({ x, label }) => (
            <text
              key={label}
              x={x}
              y={14}
              fontSize="8.5"
              fill="var(--color-text-muted)"
              textAnchor="middle"
            >
              {label}
            </text>
          ))}

          {/* Band headers + separators */}
          {layout.bands.map((band) => (
            <g key={band.family}>
              <text
                x={4}
                y={(band.y0 + band.y1) / 2 + 3}
                fontSize="9"
                fontWeight={600}
                fill="var(--color-text-muted)"
              >
                {band.label}
              </text>
              <line
                x1={0}
                y1={band.y1}
                x2={layout.width}
                y2={band.y1}
                stroke="var(--color-border)"
                strokeWidth={1}
                opacity={0.5}
              />
            </g>
          ))}

          {/* Edges: one <g>, quadratic beziers, low opacity */}
          <g>
            {layout.edges.map((e, i) => {
              const s = positionById.get(e.source);
              const t = positionById.get(e.target);
              if (!s || !t) return null;
              const hot =
                hoveredId != null && (e.source === hoveredId || e.target === hoveredId);
              return (
                <path
                  key={`${e.source}-${e.target}-${i}`}
                  d={edgeBezierPath(s.x, s.y, t.x, t.y, e.sameBand)}
                  fill="none"
                  stroke={hot ? "var(--color-info)" : "var(--color-text-muted)"}
                  strokeWidth={hot ? 1.4 : 1}
                  opacity={hot ? 0.9 : hoveredId != null ? 0.06 : 0.18}
                />
              );
            })}
          </g>

          {/* Nodes (fill) + transparent hit-target overlay, event-delegated */}
          <g onMouseOver={handleMouseOver} onMouseOut={handleMouseOut}>
            {layout.nodes.map((n) => {
              const dimmed = isDimmed(n.id);
              const highlighted = isHighlighted(n.id);
              const assumed = isAssumed(n.id);
              return (
                <circle
                  key={n.id}
                  data-node-id={n.id}
                  cx={n.x}
                  cy={n.y}
                  r={highlighted ? NODE_R + 1 : NODE_R}
                  fill={colorFor(n)}
                  stroke={assumed ? "var(--color-primary)" : "none"}
                  strokeWidth={assumed ? 1.5 : 0}
                  opacity={dimmed ? 0.15 : 1}
                  style={{ cursor: "pointer" }}
                />
              );
            })}
            {layout.nodes.map((n) => (
              <circle
                key={`hit-${n.id}`}
                data-node-id={n.id}
                cx={n.x}
                cy={n.y}
                r={HIT_R}
                fill="transparent"
                tabIndex={0}
                style={{ cursor: "pointer" }}
              />
            ))}
          </g>
        </svg>

        {hoveredMarket && hoveredNode && (
          <Tooltip market={hoveredMarket} node={hoveredNode} layout={layout} assumptionMode={assumptionMode} />
        )}

        {selectedMarket && selectedNode && (
          <NodePopover
            market={selectedMarket}
            node={selectedNode}
            layout={layout}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
}

function LegendChip({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
      {label}
    </span>
  );
}

function Tooltip({
  market,
  node,
  layout,
  assumptionMode,
}: {
  market: GraphMarket;
  node: PositionedMapNode;
  layout: MapLayout;
  assumptionMode: boolean;
}) {
  const p = displayProbability(market);
  const delta = deltaOf(market);
  return (
    <div
      role="tooltip"
      style={{
        position: "absolute",
        left: `${(node.x / layout.width) * 100}%`,
        top: `${((node.y + 8) / layout.height) * 100}%`,
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
      <div style={{ fontWeight: 600, marginBottom: 2 }}>{market.title}</div>
      {p != null && (
        <div>
          {(p * 100).toFixed(1)}%
          {assumptionMode && delta != null && Math.abs(delta) >= 0.005 && (
            <span style={{ marginLeft: 6, color: delta > 0 ? "var(--color-success)" : "var(--color-danger)" }}>
              {delta > 0 ? "+" : ""}
              {(delta * 100).toFixed(1)} pts under your assumptions
            </span>
          )}
        </div>
      )}
      <div style={{ color: "var(--color-text-muted)" }}>{sourceTag(market)}</div>
    </div>
  );
}

function NodePopover({
  market,
  node,
  layout,
  onClose,
}: {
  market: GraphMarket;
  node: PositionedMapNode;
  layout: MapLayout;
  onClose: () => void;
}) {
  const assumptionState = useOptionalAssumptions();
  const p = displayProbability(market);
  const variableId = market.variableId;
  const assumed = variableId ? assumptionState?.hasAssumption(variableId) : false;
  const leftPct = Math.min(90, Math.max(10, (node.x / layout.width) * 100));

  return (
    <div
      role="dialog"
      style={{
        position: "absolute",
        left: `${leftPct}%`,
        top: `${Math.min(88, ((node.y + 10) / layout.height) * 100)}%`,
        transform: "translateX(-50%)",
        width: 280,
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

      {p != null && (
        <div style={{ margin: "6px 0", fontSize: "1.05rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
          {(p * 100).toFixed(1)}%
        </div>
      )}

      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {assumptionState && variableId && market.status === "active" && (
          assumed ? (
            <button
              type="button"
              onClick={() => assumptionState.removeAssumption(variableId)}
              style={assumeBtnStyle(true)}
            >
              Clear assumption
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={() =>
                  assumptionState.addAssumption({ variableId, outcomeId: "yes", label: market.title })
                }
                style={assumeBtnStyle(false)}
              >
                Assume YES
              </button>
              <button
                type="button"
                onClick={() =>
                  assumptionState.addAssumption({ variableId, outcomeId: "no", label: market.title })
                }
                style={assumeBtnStyle(false)}
              >
                Assume NO
              </button>
            </>
          )
        )}
        <Link
          to={`/markets/${market.id}`}
          style={{ marginLeft: "auto", fontSize: "0.7rem", fontWeight: 600, color: "var(--color-primary)", textDecoration: "none" }}
        >
          Open market →
        </Link>
      </div>
    </div>
  );
}

function assumeBtnStyle(active: boolean): React.CSSProperties {
  return {
    padding: "3px 10px",
    borderRadius: 4,
    fontSize: "0.7rem",
    fontWeight: 600,
    cursor: "pointer",
    border: `1px solid ${active ? "var(--color-primary)" : "var(--color-border)"}`,
    background: active ? "var(--color-primary)" : "transparent",
    color: active ? "#fff" : "var(--color-text)",
  };
}

const panelStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const toolbarStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-sm)",
  marginBottom: "var(--space-sm)",
};

const legendRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-md)",
  marginBottom: "var(--space-sm)",
};

const searchInputStyle: React.CSSProperties = {
  marginLeft: "auto",
  width: 180,
  padding: "2px 8px",
  fontSize: "0.72rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
};
