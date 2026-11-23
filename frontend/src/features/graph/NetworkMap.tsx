import { useMemo, useState, useCallback, useRef, type MouseEvent, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { useGraphMarkets } from "@/lib/query/hooks";
import { ErrorMessage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import { useOptionalAssumptions } from "@/features/assumptions/AssumptionContext";
import type { GraphMarket, GraphMarketsResponse } from "@/lib/api/types";
import {
  computeMapLayout,
  edgeBezierPath,
  colorForGroup,
  deltaToColor,
  sourceTag,
  searchMatchIds,
  probabilityFillOpacity,
  probabilityRadius,
  isContextContradictedError,
  selectSnapshotKpis,
  selectWhatIfScenarios,
  GROUP_COLORS,
  GROUP_LABELS,
  type GroupKey,
  type PositionedMapNode,
  type MapLayout,
} from "./mapLayout";

// ---------------------------------------------------------------------------
// The landing hero: every market (~900) and every CPT edge (~1000-1500) on
// one structured timeline map -- X = resolution year, Y = fixed family
// bands. All data comes from the single bulk useGraphMarkets response; no
// per-node queries.
// ---------------------------------------------------------------------------

const NODE_R = 3.5;
const HIT_R = 7;
const MAX_MATCH_PILLS = 8;

function displayProbability(market: GraphMarket): number | null {
  const p = market.conditionalMarginals?.yes ?? market.marginals?.yes;
  return typeof p === "number" ? p : null;
}

function baseProbability(market: GraphMarket): number | null {
  const p = market.marginals?.yes;
  return typeof p === "number" ? p : null;
}

function deltaOf(market: GraphMarket): number | null {
  if (!market.conditionalMarginals) return null;
  const base = market.marginals?.yes;
  const cond = market.conditionalMarginals.yes;
  if (typeof base !== "number" || typeof cond !== "number") return null;
  return cond - base;
}

function causalSummary(parents: number, children: number): string {
  const pLabel = parents === 0 ? "Root driver" : `${parents} cause${parents === 1 ? "" : "s"}`;
  const cLabel = `${children} effect${children === 1 ? "" : "s"}`;
  return `${pLabel} · ${cLabel}`;
}

export function NetworkMap() {
  const assumptionState = useOptionalAssumptions();
  const assumptions = assumptionState?.assumptions ?? [];
  const context = assumptionState?.contextPayload ?? [];
  const assumptionMode = context.length > 0;

  const { data, isLoading, error } = useGraphMarkets(context);

  // Preserve the last valid network snapshot so a 409 context_contradicted (or
  // transient error) NEVER wipes the map into an error page.
  const lastGoodRef = useRef<GraphMarketsResponse | undefined>(undefined);
  if (data && data.markets.length > 0) {
    lastGoodRef.current = data;
  }
  const effectiveData = data ?? lastGoodRef.current;
  const markets = useMemo(() => effectiveData?.markets ?? [], [effectiveData]);
  const contradicted = assumptionMode && isContextContradictedError(error);

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

  const snapshotKpis = useMemo(() => selectSnapshotKpis(markets, 5), [markets]);
  const whatIfScenarios = useMemo(() => selectWhatIfScenarios(markets), [markets]);

  const presentGroups = useMemo(() => {
    const seen = new Set<GroupKey>();
    const ordered: GroupKey[] = [];
    for (const band of layout.bands) {
      if (!seen.has(band.group)) {
        seen.add(band.group);
        ordered.push(band.group);
      }
    }
    return ordered;
  }, [layout.bands]);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const activeId = hoveredId ?? selectedId;
  const neighborSet = activeId ? layout.neighborsOf.get(activeId) ?? new Set<string>() : null;
  const matchIds = searchMatchIds(query, markets);

  const matchedMarkets = useMemo(() => {
    if (!matchIds || matchIds.size === 0) return [];
    return markets.filter((m) => matchIds.has(m.id));
  }, [matchIds, markets]);

  const isDimmed = useCallback(
    (id: string) => {
      const dimmedByHover = activeId != null && id !== activeId && !neighborSet?.has(id);
      const dimmedBySearch = matchIds != null && !matchIds.has(id);
      return dimmedByHover || dimmedBySearch;
    },
    [activeId, neighborSet, matchIds],
  );

  const isHighlighted = useCallback(
    (id: string) => activeId != null && (id === activeId || (neighborSet?.has(id) ?? false)),
    [activeId, neighborSet],
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
    () => new Set(assumptions.map((a) => a.variableId)),
    [assumptions],
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
  const handleKeyDown = useCallback((e: KeyboardEvent<SVGGElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      const id = (e.target as SVGElement).getAttribute?.("data-node-id");
      if (id) {
        e.preventDefault();
        setSelectedId((prev) => (prev === id ? null : id));
      }
    } else if (e.key === "Escape") {
      setSelectedId(null);
    }
  }, []);

  const yearTicks = useMemo(() => {
    const ticks: number[] = [];
    for (let y = layout.yearMin; y <= layout.yearMax; y++) ticks.push(y);
    return ticks;
  }, [layout.yearMin, layout.yearMax]);

  if (isLoading && !effectiveData) {
    return (
      <div style={panelStyle}>
        <div style={{ color: "var(--color-text-muted)", textAlign: "center", padding: "var(--space-lg)" }}>
          Loading network…
        </div>
      </div>
    );
  }

  if (error && !effectiveData) {
    return <div style={panelStyle}><ErrorMessage message="Failed to load the market network" /></div>;
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
  const lastAssumption = assumptions[assumptions.length - 1];

  return (
    <div style={{ display: "grid", gap: "var(--space-md)", minWidth: 0 }}>
      {/* World-Model Snapshot KPI strip + one-click Try What-If scenarios */}
      {(snapshotKpis.length > 0 || (assumptionState && whatIfScenarios.length > 0)) && (
        <div style={snapshotStripStyle} data-testid="world-model-snapshot">
          {snapshotKpis.length > 0 && (
            <div style={kpiGridStyle}>
              {snapshotKpis.map(({ label, market }) => {
                const p = displayProbability(market);
                const d = assumptionMode ? deltaOf(market) : null;
                const isSelected = selectedId === market.id;
                return (
                  <button
                    key={market.id}
                    type="button"
                    onClick={() => setSelectedId(market.id)}
                    style={kpiCardStyle(isSelected)}
                  >
                    <span style={{ fontSize: "0.7rem", color: "var(--color-text-muted)", lineHeight: 1.25 }}>
                      {label}
                    </span>
                    <span style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 4 }}>
                      <span style={{ fontSize: "1.1rem", fontWeight: 700, fontVariantNumeric: "tabular-nums", color: "var(--color-text)" }}>
                        {p != null ? `${(p * 100).toFixed(1)}%` : "—"}
                      </span>
                      {d != null && Math.abs(d) >= 0.005 && (
                        <span
                          style={{
                            fontSize: "0.72rem",
                            fontWeight: 700,
                            fontVariantNumeric: "tabular-nums",
                            color: d > 0 ? "var(--color-success)" : "var(--color-danger)",
                          }}
                        >
                          {d > 0 ? "+" : ""}{(d * 100).toFixed(1)} pts
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {assumptionState && whatIfScenarios.length > 0 && (
            <div style={whatIfRowStyle}>
              <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)" }}>
                Try What-If:
              </span>
              {whatIfScenarios.map((scenario) => {
                const isActive =
                  assumptions.length === 1 &&
                  assumptions[0]?.variableId === scenario.variableId &&
                  assumptions[0]?.outcomeId === scenario.outcomeId;
                return (
                  <button
                    key={scenario.variableId}
                    type="button"
                    onClick={() => {
                      if (isActive) {
                        assumptionState.removeAssumption(scenario.variableId);
                      } else {
                        assumptionState.setAllAssumptions([
                          {
                            variableId: scenario.variableId,
                            outcomeId: scenario.outcomeId,
                            label: scenario.assumptionLabel,
                          },
                        ]);
                      }
                    }}
                    style={whatIfBtnStyle(isActive)}
                  >
                    {isActive ? `✓ ${scenario.label}` : scenario.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      <div style={panelStyle}>
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
                  Undo last assumption
                </button>
              )}
              {assumptionState && (
                <button
                  type="button"
                  onClick={assumptionState.clearAll}
                  style={bannerBtnStyle}
                >
                  Clear all
                </button>
              )}
            </div>
          </div>
        )}

        {error && !contradicted && <ReconnectingHint />}

        <div style={toolbarStyle}>
          <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>
            {markets.length.toLocaleString()} markets · {layout.edges.length.toLocaleString()} links
          </span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {matchIds != null && (
              <span style={{ fontSize: "0.72rem", color: "var(--color-text-muted)", fontVariantNumeric: "tabular-nums" }}>
                {matchIds.size} {matchIds.size === 1 ? "match" : "matches"}
              </span>
            )}
            <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setQuery("");
                  else if (e.key === "Enter" && matchedMarkets[0]) setSelectedId(matchedMarkets[0].id);
                }}
                placeholder="Search markets…"
                aria-label="Search markets"
                style={searchInputStyle}
              />
              {query.length > 0 && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  aria-label="Clear search"
                  style={clearSearchBtnStyle}
                >
                  ×
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Clickable match pills when searching so below-the-fold matches are one click away */}
        {matchedMarkets.length > 0 && (
          <div style={matchPillBarStyle} aria-label="Search matches">
            {matchedMarkets.slice(0, MAX_MATCH_PILLS).map((m) => {
              const p = displayProbability(m);
              const isSelected = selectedId === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setSelectedId(m.id)}
                  style={matchPillStyle(isSelected)}
                  title={m.title}
                >
                  <span style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {m.title}
                  </span>
                  {p != null && (
                    <span style={{ fontFamily: "var(--font-mono)", color: isSelected ? "#fff" : "var(--color-info)" }}>
                      {(p * 100).toFixed(0)}%
                    </span>
                  )}
                </button>
              );
            })}
            {matchedMarkets.length > MAX_MATCH_PILLS && (
              <span style={{ fontSize: "0.7rem", color: "var(--color-text-muted)", alignSelf: "center" }}>
                +{matchedMarkets.length - MAX_MATCH_PILLS} more
              </span>
            )}
          </div>
        )}

        {/* Legend: resting group + probability scale OR assumption delta scale */}
        {assumptionMode ? (
          <div style={legendRowStyle}>
            <LegendChip color="#d75928" label="Fell under your assumptions" />
            <LegendChip color="#6b7280" label="No meaningful change" />
            <LegendChip color="#0095d7" label="Rose under your assumptions" />
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
              <span style={{ width: 10, height: 10, borderRadius: "50%", border: "2px solid var(--color-primary)", display: "inline-block" }} />
              Assumed
            </span>
          </div>
        ) : (
          <div style={legendRowStyle}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 12px", alignItems: "center" }}>
              {presentGroups.map((g) => (
                <LegendChip key={g} color={GROUP_COLORS[g]} label={GROUP_LABELS[g]} />
              ))}
            </div>
            <div style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8, fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
              <span>P(yes):</span>
              {[
                { label: "5%", p: 0.05 },
                { label: "25%", p: 0.25 },
                { label: "50%", p: 0.5 },
                { label: "90%", p: 0.9 },
              ].map((step) => (
                <span key={step.label} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                  <span
                    aria-hidden="true"
                    style={{
                      width: Math.round(probabilityRadius(step.p, NODE_R) * 2),
                      height: Math.round(probabilityRadius(step.p, NODE_R) * 2),
                      borderRadius: "50%",
                      display: "inline-block",
                      background: `rgba(0, 131, 196, ${probabilityFillOpacity(step.p)})`,
                      border: `1px solid ${GROUP_COLORS.agi_rampup}`,
                    }}
                  />
                  <span style={{ fontVariantNumeric: "tabular-nums" }}>{step.label}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        <div style={{ position: "relative", overflowX: "auto", maxWidth: "100%" }}>
          <svg
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            style={{ width: "100%", minWidth: 960, height: "auto", display: "block", userSelect: "none" }}
            role="img"
            aria-label="Full belief network of all markets"
            onClick={handleClick}
          >
            <defs>
              {/* Directional arrowhead for highlighted causal edges (polygon keeps path count == edge count) */}
              <marker
                id="nm-arrow-hot"
                viewBox="0 0 8 8"
                refX="10"
                refY="4"
                markerWidth="6"
                markerHeight="6"
                orient="auto"
              >
                <polygon points="0,1 7.5,4 0,7" fill="var(--color-info)" />
              </marker>
            </defs>

            {/* Year gridlines + labels */}
            {yearTicks.map((year) => {
              const x = layout.yearToX(year);
              return (
                <g key={year}>
                  <line
                    x1={x}
                    y1={18}
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

            {/* Band headers, group accent bar, sub-row threshold labels, and separators */}
            {layout.bands.map((band) => (
              <g key={band.family}>
                {/* Subtle left accent bar matching band's categorical group */}
                <rect
                  x={0}
                  y={band.y0 + 2}
                  width={3}
                  height={Math.max(4, band.y1 - band.y0 - 4)}
                  rx={1.5}
                  fill={colorForGroup(band.group)}
                  opacity={0.85}
                />
                <text
                  x={7}
                  y={(band.y0 + band.y1) / 2 + 3}
                  fontSize="8.8"
                  fontWeight={600}
                  fill="var(--color-text)"
                  opacity={0.85}
                >
                  {band.label}
                </text>
                {/* Sub-row threshold labels + subtle guide hairlines for multi-tier bands */}
                {band.subRows.map((sub) => (
                  <g key={`${band.family}-t${sub.tier}`}>
                    <line
                      x1={layout.leftMargin - 8}
                      y1={sub.y}
                      x2={layout.width - 8}
                      y2={sub.y}
                      stroke="var(--color-border)"
                      strokeWidth={0.75}
                      opacity={0.18}
                    />
                    <text
                      x={layout.leftMargin - 12}
                      y={sub.y + 2.5}
                      fontSize="7.4"
                      fontFamily="var(--font-mono)"
                      fill="var(--color-text-muted)"
                      textAnchor="end"
                    >
                      {sub.label}
                    </text>
                  </g>
                ))}
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

            {/* Edges: one <g>, quadratic beziers with directional arrowheads on highlight */}
            <g>
              {layout.edges.map((e, i) => {
                const s = positionById.get(e.source);
                const t = positionById.get(e.target);
                if (!s || !t) return null;
                const hot = activeId != null && (e.source === activeId || e.target === activeId);
                const searchDimmed =
                  matchIds != null && !matchIds.has(e.source) && !matchIds.has(e.target);
                const searchMatched =
                  matchIds != null && (matchIds.has(e.source) || matchIds.has(e.target));
                const opacity = hot
                  ? 0.92
                  : searchDimmed
                    ? 0.04
                    : activeId != null
                      ? 0.06
                      : searchMatched
                        ? 0.35
                        : 0.16;
                return (
                  <path
                    key={`${e.source}-${e.target}-${i}`}
                    d={edgeBezierPath(s.x, s.y, t.x, t.y, e.sameBand)}
                    fill="none"
                    stroke={hot ? "var(--color-info)" : "var(--color-text-muted)"}
                    strokeWidth={hot ? 1.5 : 1}
                    opacity={opacity}
                    markerEnd={hot ? "url(#nm-arrow-hot)" : undefined}
                  />
                );
              })}
            </g>

            {/* Nodes (fill) + keyboard/selected ring + transparent hit-target overlay */}
            <g
              onMouseOver={handleMouseOver}
              onMouseOut={handleMouseOut}
              onKeyDown={handleKeyDown}
            >
              {layout.nodes.map((n) => {
                const market = marketById.get(n.id);
                const p = market ? displayProbability(market) : null;
                const dimmed = isDimmed(n.id);
                const highlighted = isHighlighted(n.id);
                const assumed = isAssumed(n.id);
                const color = colorFor(n);
                const r = highlighted
                  ? NODE_R + 1.2
                  : assumptionMode
                    ? NODE_R
                    : probabilityRadius(p, NODE_R);
                const fillOpacity = assumptionMode ? 1 : probabilityFillOpacity(p);
                const ringOpacity = assumptionMode ? 1 : 0.45 + 0.55 * (p ?? 0.5);
                return (
                  <circle
                    key={n.id}
                    data-node-id={n.id}
                    cx={n.x}
                    cy={n.y}
                    r={r}
                    fill={color}
                    fillOpacity={fillOpacity}
                    stroke={assumed ? "var(--color-primary)" : assumptionMode ? "none" : color}
                    strokeWidth={assumed ? 1.8 : assumptionMode ? 0 : 0.9}
                    strokeOpacity={assumed ? 1 : ringOpacity}
                    opacity={dimmed ? 0.15 : 1}
                    style={{ cursor: "pointer" }}
                  />
                );
              })}

              {/* Clean SVG ring for selected or keyboard-focused node (replaces rectangular focus outline) */}
              {(focusedId || selectedId) &&
                [focusedId, selectedId]
                  .filter((id, idx, arr): id is string => id != null && arr.indexOf(id) === idx)
                  .map((id) => {
                    const n = positionById.get(id);
                    if (!n) return null;
                    return (
                      <circle
                        key={`ring-${id}`}
                        cx={n.x}
                        cy={n.y}
                        r={NODE_R + 3}
                        fill="none"
                        stroke="var(--color-primary)"
                        strokeWidth={1.6}
                        pointerEvents="none"
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
                  aria-label={marketById.get(n.id)?.title ?? n.id}
                  onFocus={() => setFocusedId(n.id)}
                  onBlur={() => setFocusedId((prev) => (prev === n.id ? null : prev))}
                  style={{ cursor: "pointer", outline: "none" }}
                />
              ))}
            </g>
          </svg>

          {hoveredMarket && hoveredNode && (
            <Tooltip
              market={hoveredMarket}
              node={hoveredNode}
              layout={layout}
              assumptionMode={assumptionMode}
              parentCount={layout.parentsOf.get(hoveredMarket.id)?.length ?? 0}
              childCount={layout.childrenOf.get(hoveredMarket.id)?.length ?? 0}
            />
          )}

          {selectedMarket && selectedNode && (
            <NodePopover
              market={selectedMarket}
              node={selectedNode}
              layout={layout}
              assumptionMode={assumptionMode}
              parentCount={layout.parentsOf.get(selectedMarket.id)?.length ?? 0}
              childCount={layout.childrenOf.get(selectedMarket.id)?.length ?? 0}
              onClose={() => setSelectedId(null)}
            />
          )}
        </div>
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
  parentCount,
  childCount,
}: {
  market: GraphMarket;
  node: PositionedMapNode;
  layout: MapLayout;
  assumptionMode: boolean;
  parentCount: number;
  childCount: number;
}) {
  const p = displayProbability(market);
  const delta = deltaOf(market);
  const xRatio = node.x / layout.width;
  const yRatio = node.y / layout.height;
  const flipLeft = xRatio > 0.72;
  const nearLeft = xRatio < 0.2;
  const flipUp = yRatio > 0.76;
  const tx = flipLeft ? "-95%" : nearLeft ? "-5%" : "-50%";
  const ty = flipUp ? "calc(-100% - 14px)" : "0px";

  return (
    <div
      role="tooltip"
      style={{
        position: "absolute",
        left: `${xRatio * 100}%`,
        top: `${((node.y + 8) / layout.height) * 100}%`,
        transform: `translate(${tx}, ${ty})`,
        maxWidth: 270,
        padding: "7px 10px",
        borderRadius: 6,
        border: "1px solid var(--color-border)",
        background: "var(--color-bg)",
        fontSize: "0.72rem",
        color: "var(--color-text)",
        pointerEvents: "none",
        zIndex: 5,
        boxShadow: "0 4px 14px rgba(0,0,0,0.45)",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 3, lineHeight: 1.3 }}>{market.title}</div>
      {p != null && (
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 3 }}>
          <span style={{ fontWeight: 700, fontSize: "0.82rem", fontVariantNumeric: "tabular-nums" }}>
            {(p * 100).toFixed(1)}%
          </span>
          {assumptionMode && delta != null && Math.abs(delta) >= 0.005 && (
            <span style={{ fontWeight: 600, fontVariantNumeric: "tabular-nums", color: delta > 0 ? "var(--color-success)" : "var(--color-danger)" }}>
              {delta > 0 ? "+" : ""}
              {(delta * 100).toFixed(1)} pts under your assumptions
            </span>
          )}
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--color-text-muted)", fontSize: "0.68rem" }}>
        <span>{causalSummary(parentCount, childCount)}</span>
        <span style={sourceBadgeStyle}>{sourceTag(market)}</span>
      </div>
    </div>
  );
}

function NodePopover({
  market,
  node,
  layout,
  assumptionMode,
  parentCount,
  childCount,
  onClose,
}: {
  market: GraphMarket;
  node: PositionedMapNode;
  layout: MapLayout;
  assumptionMode: boolean;
  parentCount: number;
  childCount: number;
  onClose: () => void;
}) {
  const assumptionState = useOptionalAssumptions();
  const p = displayProbability(market);
  const baseP = baseProbability(market);
  const delta = assumptionMode ? deltaOf(market) : null;
  const variableId = market.variableId;
  const assumed = variableId ? assumptionState?.hasAssumption(variableId) : false;

  const isCertainYes = p != null && p >= 0.9995;
  const isCertainNo = p != null && p <= 0.0005;

  // Edge-safe positioning: flip left near the right edge, flip up near the bottom edge.
  const xRatio = node.x / layout.width;
  const yRatio = node.y / layout.height;
  const flipLeft = xRatio > 0.72;
  const nearLeft = xRatio < 0.22;
  const flipUp = yRatio > 0.74;
  const tx = flipLeft ? "-96%" : nearLeft ? "-4%" : "-50%";
  const ty = flipUp ? "calc(-100% - 16px)" : "0px";

  const showPriorToPosterior =
    assumptionMode && baseP != null && p != null && market.conditionalMarginals != null;

  return (
    <div
      role="dialog"
      data-flip-left={flipLeft ? "true" : "false"}
      style={{
        position: "absolute",
        left: `${Math.min(98, Math.max(2, xRatio * 100))}%`,
        top: `${Math.min(94, ((node.y + 10) / layout.height) * 100)}%`,
        transform: `translate(${tx}, ${ty})`,
        width: 290,
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

      {showPriorToPosterior ? (
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap", margin: "6px 0", fontVariantNumeric: "tabular-nums" }}>
          <span style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
            {(baseP * 100).toFixed(1)}%
          </span>
          <span style={{ color: "var(--color-text-muted)" }}>→</span>
          <span style={{ fontSize: "1.05rem", fontWeight: 700 }}>
            {(p * 100).toFixed(1)}%
          </span>
          {delta != null && Math.abs(delta) >= 0.0005 && (
            <span
              style={{
                fontSize: "0.75rem",
                fontWeight: 700,
                color: delta > 0 ? "var(--color-success)" : "var(--color-danger)",
              }}
            >
              ({delta > 0 ? "+" : ""}{(delta * 100).toFixed(1)} pts)
            </span>
          )}
        </div>
      ) : p != null ? (
        <div style={{ margin: "6px 0", fontSize: "1.05rem", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>
          {(p * 100).toFixed(1)}%
        </div>
      ) : null}

      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.68rem", color: "var(--color-text-muted)", marginBottom: 4 }}>
        <span>{causalSummary(parentCount, childCount)}</span>
        <span style={sourceBadgeStyle}>{sourceTag(market)}</span>
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {assumptionState && variableId && market.status === "active" && (
          assumed ? (
            <button
              type="button"
              onClick={() => assumptionState.removeAssumption(variableId)}
              style={assumeBtnStyle(true, false)}
            >
              Clear assumption
            </button>
          ) : (
            <>
              <button
                type="button"
                disabled={isCertainNo}
                title={isCertainNo ? "Certain under current assumptions" : undefined}
                onClick={() =>
                  assumptionState.addAssumption({ variableId, outcomeId: "yes", label: market.title })
                }
                style={assumeBtnStyle(false, isCertainNo)}
              >
                Assume YES
              </button>
              <button
                type="button"
                disabled={isCertainYes}
                title={isCertainYes ? "Certain under current assumptions" : undefined}
                onClick={() =>
                  assumptionState.addAssumption({ variableId, outcomeId: "no", label: market.title })
                }
                style={assumeBtnStyle(false, isCertainYes)}
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

      {!assumed && (isCertainYes || isCertainNo) && (
        <div style={{ marginTop: 6, fontSize: "0.68rem", color: "var(--color-text-muted)" }}>
          Certain under current assumptions
        </div>
      )}
    </div>
  );
}

function assumeBtnStyle(active: boolean, disabled: boolean): React.CSSProperties {
  return {
    padding: "3px 10px",
    borderRadius: 4,
    fontSize: "0.7rem",
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.45 : 1,
    border: `1px solid ${active ? "var(--color-primary)" : "var(--color-border)"}`,
    background: active ? "var(--color-primary)" : "transparent",
    color: active ? "#fff" : "var(--color-text)",
  };
}

const snapshotStripStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-sm)",
  minWidth: 0,
};

const kpiGridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: "var(--space-sm)",
};

function kpiCardStyle(selected: boolean): React.CSSProperties {
  return {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    padding: "10px 12px",
    borderRadius: "var(--radius-md)",
    border: `1px solid ${selected ? "var(--color-primary)" : "var(--color-border)"}`,
    background: "var(--color-bg-surface)",
    cursor: "pointer",
    textAlign: "left",
    transition: "border-color 0.15s",
  };
}

const whatIfRowStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 8,
};

function whatIfBtnStyle(active: boolean): React.CSSProperties {
  return {
    padding: "4px 10px",
    borderRadius: 999,
    border: `1px solid ${active ? "var(--color-primary)" : "var(--color-border)"}`,
    background: active ? "var(--color-primary)" : "var(--color-bg-surface)",
    color: active ? "#fff" : "var(--color-text)",
    fontSize: "0.75rem",
    fontWeight: 500,
    cursor: "pointer",
  };
}

const panelStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
  minWidth: 0,
};

const toolbarStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: "var(--space-sm)",
  marginBottom: "var(--space-sm)",
};

const legendRowStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "6px 14px",
  marginBottom: "var(--space-sm)",
};

const searchInputStyle: React.CSSProperties = {
  width: 190,
  padding: "3px 22px 3px 8px",
  fontSize: "0.74rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
};

const clearSearchBtnStyle: React.CSSProperties = {
  position: "absolute",
  right: 4,
  background: "transparent",
  border: "none",
  color: "var(--color-text-muted)",
  cursor: "pointer",
  fontSize: "0.85rem",
  lineHeight: 1,
  padding: "0 3px",
};

const matchPillBarStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  marginBottom: "var(--space-sm)",
};

function matchPillStyle(selected: boolean): React.CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "3px 8px",
    borderRadius: 999,
    border: `1px solid ${selected ? "var(--color-primary)" : "var(--color-border)"}`,
    background: selected ? "var(--color-primary)" : "var(--color-bg)",
    color: selected ? "#fff" : "var(--color-text)",
    fontSize: "0.7rem",
    cursor: "pointer",
  };
}

const sourceBadgeStyle: React.CSSProperties = {
  marginLeft: "auto",
  padding: "1px 6px",
  borderRadius: 999,
  background: "var(--color-bg-hover)",
  color: "var(--color-text-muted)",
  fontSize: "0.64rem",
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
  padding: "3px 9px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.72rem",
  fontWeight: 600,
  cursor: "pointer",
};
