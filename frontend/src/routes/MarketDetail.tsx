import { useState, useCallback, useMemo, useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  useMarket,
  useMarkets,
  useMarketEvents,
  useAccountRisk,
  useEngineStats,
  useNetwork,
  useGraphMarkets,
  queryKeys,
} from "@/lib/query/hooks";
import { useSession } from "@/features/session/context";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ProbabilityBar } from "@/components/ui/ProbabilityBar";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import { FormattedDescription } from "@/components/ui/FormattedDescription";
import { formatCurrency, timeUntil, truncateHash, formatRelativeTime } from "@/lib/utils/format";
import { AssumptionProvider, useAssumptions, useOptionalAssumptions } from "@/features/assumptions/AssumptionContext";
import { AssumptionBar } from "@/features/assumptions/AssumptionBar";
import { AssumptionPanel } from "@/features/assumptions/AssumptionPanel";
import { HistoryProvider } from "@/features/history/HistoryContext";
import { UndoRedoToolbar } from "@/features/history/UndoRedoToolbar";
import { ForceDirectedGraph } from "@/features/graph/ForceDirectedGraph";
import { BeliefFlowGraph } from "@/features/graph/BeliefFlowGraph";
import { GraphToolbar, type GraphView } from "@/features/graph/GraphToolbar";
import { deriveEdgesFromCliques } from "@/features/graph/deriveEdges";
import { buildNetworkExport, downloadJson } from "@/features/graph/networkExport";
import { isContextContradictedError } from "@/features/graph/mapLayout";
import { JunctionTreePanel } from "@/features/graph/JunctionTreePanel";
import { DiscussionThread } from "@/features/market/DiscussionThread";
import { ResolveMarketPanel } from "@/features/market/ResolveMarketPanel";
import { EventTradePanel } from "@/features/trading/EventTradePanel";
import { CptPanel } from "@/features/trading/CptPanel";
import type { GraphMarket, Market, MarketEvent, MarketSummary, NetworkEdgeSummary } from "@/lib/api/types";
import { TradeCreditsPanel } from "@/lib/exchange/TradeCreditsPanel";
import { isExchangeMode } from "@/lib/exchangeMode";
import { useInstruments } from "@/lib/exchange/hooks";
import { VenuePanels } from "@/routes/InstrumentDetail";
import { MarketCombobox } from "@/features/compare/MarketCombobox";
import { RelatedMarketChips } from "@/features/compare/RelatedMarketChips";

export default function MarketDetail() {
  const { marketId } = useParams<{ marketId: string }>();
  const exchangeMode = isExchangeMode();
  const { session, isConfigured } = useSession();
  const { data, isLoading, error } = useMarket(marketId!);
  const events = useMarketEvents(marketId!, { enabled: !exchangeMode });
  const accountRisk = useAccountRisk(session.accountId, { enabled: !exchangeMode });

  // All hooks must run unconditionally (before the loading/error returns
  // below) so their order is stable across renders — see React error #310.

  // Track which market's CPT to display when a graph node is clicked (paper mode).
  const [selectedMarketId, setSelectedMarketId] = useState<string | null>(null);
  const effectiveSelectedId = selectedMarketId ?? marketId!;
  const selectedMarketQuery = useMarket(effectiveSelectedId, {
    enabled: !exchangeMode && effectiveSelectedId !== marketId,
  });

  const handleNodeClick = useCallback((nodeId: string) => {
    setSelectedMarketId(nodeId);
  }, []);

  // Graph view toggle and toolbar state
  const [graphView, setGraphView] = useState<GraphView>("flow");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const marketsQuery = useMarkets();
  const networkQuery = useNetwork();
  const instruments = useInstruments(exchangeMode);
  const engineStatsQuery = useEngineStats(marketId!, { enabled: !exchangeMode });
  const allMarkets = marketsQuery.data?.markets ?? [];
  const networkEdges = networkQuery.data?.edges ?? [];
  const cliques = engineStatsQuery.data?.cliques.cliques ?? [];

  const handleExport = useCallback(() => {
    const cliqueEdges = deriveEdgesFromCliques(cliques);
    const nodes = allMarkets.map((mk) => ({ id: mk.id, x: 0, y: 0 }));
    const exported = buildNetworkExport(allMarkets, nodes, cliqueEdges, [], cliques);
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadJson(exported, `bayes-network-${ts}.json`);
  }, [allMarkets, cliques]);

  const handleImportSuccess = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.marketLists() });
  }, [queryClient]);

  if (isLoading) return <LoadingPage />;
  if (error && !data) return <ErrorMessage message={error instanceof Error ? error.message : "Market not found"} />;
  if (!data) return null;

  const m = data.market;
  const instrument = exchangeMode ? instruments.data?.find((item) =>
    item.listings.some((listing) => listing.venue === "net" && listing.marketId === m.id),
  ) : undefined;
  const selectedMarket =
    effectiveSelectedId === m.id ? m : selectedMarketQuery.data?.market ?? m;
  const comparisonMarkets = [m, ...allMarkets.filter((market) => market.id !== m.id)];

  function compareWith(otherMarketId: string) {
    navigate(`/compare?a=${encodeURIComponent(m.id)}&b=${encodeURIComponent(otherMarketId)}`);
  }

  return (
    <HistoryProvider>
    <AssumptionProvider>
    <div style={{ display: "grid", gap: "var(--space-lg)", minWidth: 0 }}>
      {error && <ReconnectingHint />}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", gap: "var(--space-md)", alignItems: "center", flexWrap: "wrap", marginBottom: "var(--space-sm)" }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>{m.title}</h1>
          <StatusBadge status={m.status} />
        </div>
        <div style={compareRowStyle}>
          <div style={{ width: 260, maxWidth: "100%" }}>
            <MarketCombobox
              label="Compare with…"
              value=""
              markets={comparisonMarkets.filter((market) => market.id !== m.id)}
              onChange={compareWith}
              placeholder="Compare with…"
              showLabel={false}
            />
          </div>
          <RelatedMarketChips
            marketId={m.id}
            markets={comparisonMarkets}
            networkEdges={networkEdges}
            onSelect={compareWith}
            label="Related:"
          />
        </div>
        {m.description && (
          <p style={{ color: "var(--color-text-muted)", marginBottom: "var(--space-md)", lineHeight: 1.55, overflowWrap: "break-word" }}>
            <FormattedDescription text={m.description} />
          </p>
        )}
        {exchangeMode ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-md)", fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
            <span>Live net-venue marginals</span>
            {m.volume > 0 && <span>Volume: {formatCurrency(m.volume)} credits</span>}
            {m.liquidity > 0 && <span>Liquidity: {formatCurrency(m.liquidity)} credits</span>}
          </div>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-lg)", fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
            <span>Volume: {formatCurrency(m.volume)}</span>
            <span>Liquidity: {formatCurrency(m.liquidity)}</span>
            <span>Expires: {timeUntil(m.expires_at)}</span>
          </div>
        )}
      </div>

      <ConditionedProbabilityBar market={m} />

      {!exchangeMode && <PositionCard marketId={m.id} accountRisk={accountRisk.data} isConfigured={isConfigured} />}

      <TradeCreditsPanel marketId={m.id} variableId={m.variableId} />

      {instrument && <VenuePanels instrument={instrument} includeNet={false} />}

      {exchangeMode && (
        <CausalContextPanel
          market={m}
          allMarkets={allMarkets}
          networkEdges={networkEdges}
        />
      )}

      {!exchangeMode && <ResolveMarketPanel market={m} />}

      {!exchangeMode && m.status === "active" && (
        <>
          <UndoRedoToolbar />
          <AssumptionPanel market={m} />
          <CptPanel market={selectedMarket} />
          <EventTradePanel market={m} />
          <DiscussionThread market={m} />
        </>
      )}

      {!exchangeMode && m.status !== "active" && (
        <>
          <CptPanel market={selectedMarket} />
          <EventTradePanel market={m} />
          <DiscussionThread market={m} />
        </>
      )}

      <GraphToolbar
        view={graphView}
        onViewChange={setGraphView}
        onExport={handleExport}
        onImportSuccess={handleImportSuccess}
      />
      {graphView === "force" ? (
        <ConnectedForceGraph focusMarketId={m.id} onNodeClick={handleNodeClick} />
      ) : (
        <BeliefFlowGraph focusMarketId={m.id} onNodeClick={handleNodeClick} />
      )}

      {/* Paper-only Event Journal & Junction Tree diagnostics */}
      {!exchangeMode && (
        <div>
          <h2 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>Event Journal</h2>
          {events.isLoading && <LoadingPage />}
          {events.error && !events.data && <ErrorMessage message="Failed to load market events" />}
          {events.error && events.data && <ReconnectingHint />}
          {events.data && events.data.events.length === 0 && (
            <span style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>No events yet.</span>
          )}
          {events.data && events.data.events.length > 0 && (
            <div style={{ borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
                <thead>
                  <tr style={{ background: "var(--color-bg-hover)" }}>
                    <th style={thStyle}>Seq</th>
                    <th style={thStyle}>Type</th>
                    <th style={thStyle}>Hash</th>
                    <th style={thStyle}>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data.events.map((e) => (
                    <EventRow key={e.eventId} event={e} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {!exchangeMode && <JunctionTreePanel marketId={m.id} />}
    </div>
    </AssumptionProvider>
    </HistoryProvider>
  );
}

/**
 * Exchange-mode Causal Context & What-If panel: shows direct causal parents &
 * children with live probabilities & clickable links (zero N+1 queries), plus
 * working Assume YES / Assume NO conditioning buttons backed by a single bulk
 * conditioned graph query.
 */
function CausalContextPanel({
  market,
  allMarkets,
  networkEdges,
}: {
  market: Market;
  allMarkets: MarketSummary[];
  networkEdges: NetworkEdgeSummary[];
}) {
  const { assumptions, addAssumption, removeAssumption, clearAll, getAssumption, contextPayload } =
    useAssumptions();
  const hasAssumptions = contextPayload.length > 0;

  const conditionedGraph = useGraphMarkets(contextPayload, { enabled: hasAssumptions });
  const lastGoodRef = useRef<GraphMarket[] | undefined>(undefined);
  if (conditionedGraph?.data?.markets) {
    lastGoodRef.current = conditionedGraph.data.markets;
  }
  const graphMarkets = conditionedGraph?.data?.markets ?? (hasAssumptions ? lastGoodRef.current : undefined) ?? [];
  const graphById = useMemo(() => new Map(graphMarkets.map((gm) => [gm.id, gm])), [graphMarkets]);
  const contradicted = hasAssumptions && isContextContradictedError(conditionedGraph?.error);

  const marketById = useMemo(() => new Map(allMarkets.map((m) => [m.id, m])), [allMarkets]);

  const { parents, children } = useMemo(() => {
    const parentIds = new Set<string>();
    const childIds = new Set<string>();
    for (const e of networkEdges) {
      if (e.to === market.id && e.from !== market.id) parentIds.add(e.from);
      if (e.from === market.id && e.to !== market.id) childIds.add(e.to);
    }
    const resolve = (ids: Set<string>) =>
      Array.from(ids)
        .map((id) => marketById.get(id))
        .filter((m): m is MarketSummary => m != null);
    return { parents: resolve(parentIds), children: resolve(childIds) };
  }, [networkEdges, market.id, marketById]);

  const currentAssumed = market.variableId ? getAssumption(market.variableId) : undefined;
  const selfGraph = graphById.get(market.id);
  const displayedYes =
    (hasAssumptions ? selfGraph?.conditionalMarginals?.yes : undefined) ?? market.marginals?.yes;
  const isCertainYes = typeof displayedYes === "number" && displayedYes >= 0.9995;
  const isCertainNo = typeof displayedYes === "number" && displayedYes <= 0.0005;
  const lastAssumption = assumptions[assumptions.length - 1];

  const renderChipList = (items: MarketSummary[], emptyText: string) => {
    if (items.length === 0) {
      return <span style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>{emptyText}</span>;
    }
    return (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(min(260px, 100%), 1fr))", gap: 8 }}>
        {items.map((rel) => {
          const gm = graphById.get(rel.id);
          const baseP = gm?.marginals?.yes ?? rel.marginals?.yes;
          const condP = hasAssumptions ? gm?.conditionalMarginals?.yes : undefined;
          const deltaPts =
            typeof baseP === "number" && typeof condP === "number" ? (condP - baseP) * 100 : null;
          const shownP = typeof condP === "number" ? condP : baseP;
          return (
            <Link key={rel.id} to={`/markets/${rel.id}`} style={causalChipStyle}>
              <span style={{ fontWeight: 500, fontSize: "0.82rem", color: "var(--color-text)", lineHeight: 1.3 }}>
                {rel.title}
              </span>
              <span style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 4, fontVariantNumeric: "tabular-nums" }}>
                {typeof baseP === "number" && typeof condP === "number" && deltaPts != null && Math.abs(deltaPts) >= 0.05 ? (
                  <>
                    <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
                      {(baseP * 100).toFixed(1)}% →
                    </span>
                    <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--color-text)" }}>
                      {(condP * 100).toFixed(1)}%
                    </span>
                    <span style={{ fontSize: "0.74rem", fontWeight: 700, color: deltaPts > 0 ? "var(--color-success)" : "var(--color-danger)" }}>
                      {deltaPts > 0 ? "+" : ""}{deltaPts.toFixed(1)} pts
                    </span>
                  </>
                ) : typeof shownP === "number" ? (
                  <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--color-info)" }}>
                    {(shownP * 100).toFixed(1)}%
                  </span>
                ) : (
                  <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>—</span>
                )}
              </span>
            </Link>
          );
        })}
      </div>
    );
  };

  return (
    <section style={causalPanelStyle} aria-label="Causal Context & What-If">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "var(--space-sm)" }}>
        <div>
          <h2 style={{ fontSize: "1.1rem", fontWeight: 600 }}>Causal Context &amp; What-If</h2>
          <p style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", marginTop: 2 }}>
            Assume this outcome to see exact Bayesian updates across its direct causes and effects.
          </p>
        </div>

        {market.variableId && market.status === "active" && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              disabled={!currentAssumed && isCertainNo}
              title={!currentAssumed && isCertainNo ? "Certain under current assumptions" : undefined}
              onClick={() => {
                if (currentAssumed?.outcomeId === "yes") {
                  removeAssumption(market.variableId);
                } else {
                  addAssumption({ variableId: market.variableId, outcomeId: "yes", label: market.title });
                }
              }}
              style={whatIfToggleStyle(currentAssumed?.outcomeId === "yes", !currentAssumed && isCertainNo)}
            >
              {currentAssumed?.outcomeId === "yes" ? "✓ Assumed YES" : "Assume YES"}
            </button>
            <button
              type="button"
              disabled={!currentAssumed && isCertainYes}
              title={!currentAssumed && isCertainYes ? "Certain under current assumptions" : undefined}
              onClick={() => {
                if (currentAssumed?.outcomeId === "no") {
                  removeAssumption(market.variableId);
                } else {
                  addAssumption({ variableId: market.variableId, outcomeId: "no", label: market.title });
                }
              }}
              style={whatIfToggleStyle(currentAssumed?.outcomeId === "no", !currentAssumed && isCertainYes)}
            >
              {currentAssumed?.outcomeId === "no" ? "✓ Assumed NO" : "Assume NO"}
            </button>
          </div>
        )}
      </div>

      <AssumptionBar />

      {contradicted && (
        <div role="alert" style={contradictionBannerStyle}>
          <span>
            Contradictory assumption: those outcomes have zero joint probability in the network. Remove an assumption or Clear all.
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            {lastAssumption && (
              <button type="button" onClick={() => removeAssumption(lastAssumption.variableId)} style={bannerBtnStyle}>
                Undo last
              </button>
            )}
            <button type="button" onClick={clearAll} style={bannerBtnStyle}>
              Clear all
            </button>
          </div>
        </div>
      )}

      <div style={{ display: "grid", gap: "var(--space-md)" }}>
        <div>
          <div style={causalGroupTitleStyle}>
            Causes (Parents) · {parents.length}
          </div>
          {renderChipList(parents, "Root driver — no direct causal parents in this network.")}
        </div>

        <div>
          <div style={causalGroupTitleStyle}>
            Effects (Children) · {children.length}
          </div>
          {renderChipList(children, "Leaf market — no direct causal effects in this network.")}
        </div>
      </div>
    </section>
  );
}

/** Probability bar reflecting the active assumptions (excluding this market's own variable). */
function ConditionedProbabilityBar({ market }: { market: Market }) {
  const assumptionState = useOptionalAssumptions();
  const context = (assumptionState?.contextPayload ?? []).filter(
    (c) => c.variableId !== market.variableId,
  );
  const { data } = useMarket(market.id, { context, enabled: context.length > 0 });
  const marginals = context.length > 0 && data ? data.market.marginals : market.marginals;
  return <ProbabilityBar outcomes={market.outcomes} marginals={marginals} />;
}

function PositionCard({
  marketId,
  accountRisk,
  isConfigured,
}: {
  marketId: string;
  accountRisk: import("@/lib/api/types").AccountRiskResponse | undefined;
  isConfigured: boolean;
}) {
  if (!isConfigured || !accountRisk) return null;

  const marketRisk = accountRisk.account.risk.minAssets.markets.find(
    (mr) => mr.marketId === marketId,
  );

  if (!marketRisk) return null;

  const utilColor = marketRisk.utilization > 0.8
    ? "var(--color-danger)"
    : marketRisk.utilization > 0.5
      ? "var(--color-warning, orange)"
      : "var(--color-text)";

  return (
    <div style={positionCardStyle}>
      <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: "var(--space-xs)" }}>
        Your Position
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-sm)", fontSize: "0.8rem" }}>
        <div>
          <div style={{ color: "var(--color-text-muted)", fontSize: "0.7rem" }}>Min Asset</div>
          <div style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>{marketRisk.minAsset.toFixed(2)}</div>
        </div>
        <div>
          <div style={{ color: "var(--color-text-muted)", fontSize: "0.7rem" }}>Utilization</div>
          <div style={{ fontFamily: "var(--font-mono)", fontWeight: 600, color: utilColor }}>
            {(marketRisk.utilization * 100).toFixed(1)}%
          </div>
        </div>
        <div>
          <div style={{ color: "var(--color-text-muted)", fontSize: "0.7rem" }}>Trades</div>
          <div style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>{marketRisk.commandCount}</div>
        </div>
      </div>
    </div>
  );
}

function EventRow({ event }: { event: MarketEvent }) {
  const [expanded, setExpanded] = useState(false);
  const hasPayload = Object.keys(event.payload).length > 0;

  return (
    <>
      <tr
        onClick={() => hasPayload && setExpanded(!expanded)}
        style={{ borderTop: "1px solid var(--color-border)", cursor: hasPayload ? "pointer" : "default" }}
      >
        <td style={tdStyle}>{event.seq}</td>
        <td style={tdStyle}>
          {hasPayload && <span style={{ marginRight: 4, fontSize: "0.65rem" }}>{expanded ? "\u25BC" : "\u25B6"}</span>}
          {event.type}
        </td>
        <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>
          {truncateHash(event.eventHash)}
        </td>
        <td style={tdStyle}>{formatRelativeTime(event.timestamp)}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} style={{ padding: "0 12px 8px 12px" }}>
            <pre style={payloadStyle}>{JSON.stringify(event.payload, null, 2)}</pre>
          </td>
        </tr>
      )}
    </>
  );
}

const thStyle: React.CSSProperties = { textAlign: "left", padding: "6px 12px", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "6px 12px" };
const compareRowStyle: React.CSSProperties = { display: "flex", alignItems: "center", flexWrap: "wrap", gap: "var(--space-sm)", marginBottom: "var(--space-sm)" };

const causalPanelStyle: React.CSSProperties = {
  display: "grid",
  gap: "var(--space-md)",
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
  minWidth: 0,
};

const causalGroupTitleStyle: React.CSSProperties = {
  fontSize: "0.78rem",
  fontWeight: 600,
  color: "var(--color-text-muted)",
  marginBottom: 6,
  textTransform: "uppercase",
  letterSpacing: "0.03em",
};

const causalChipStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  padding: "8px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  textDecoration: "none",
};

function whatIfToggleStyle(active: boolean, disabled: boolean): React.CSSProperties {
  return {
    padding: "5px 12px",
    borderRadius: "var(--radius-sm)",
    border: `1px solid ${active ? "var(--color-primary)" : "var(--color-border)"}`,
    background: active ? "var(--color-primary)" : "var(--color-bg)",
    color: active ? "#fff" : "var(--color-text)",
    fontSize: "0.78rem",
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.45 : 1,
  };
}

const contradictionBannerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  flexWrap: "wrap",
  gap: 8,
  padding: "8px 12px",
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

const positionCardStyle: React.CSSProperties = {
  padding: "var(--space-sm) var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const payloadStyle: React.CSSProperties = {
  margin: 0,
  padding: "var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-bg)",
  border: "1px solid var(--color-border)",
  fontSize: "0.7rem",
  fontFamily: "var(--font-mono)",
  overflow: "auto",
  maxHeight: 200,
};

/** Bridge component: reads AssumptionContext and passes assumptions to ForceDirectedGraph */
function ConnectedForceGraph({ focusMarketId, onNodeClick }: { focusMarketId: string; onNodeClick?: (id: string) => void }) {
  const { assumptions } = useAssumptions();
  return <ForceDirectedGraph focusMarketId={focusMarketId} onNodeClick={onNodeClick} assumptions={assumptions} />;
}
