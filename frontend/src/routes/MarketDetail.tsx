import { useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useMarket, useMarkets, useMarketEvents, useAccountRisk, useEngineStats, queryKeys } from "@/lib/query/hooks";
import { useSession } from "@/features/session/context";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ProbabilityBar } from "@/components/ui/ProbabilityBar";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { formatCurrency, timeUntil, truncateHash, formatRelativeTime } from "@/lib/utils/format";
import { AssumptionProvider, useAssumptions } from "@/features/assumptions/AssumptionContext";
import { AssumptionPanel } from "@/features/assumptions/AssumptionPanel";
import { HistoryProvider } from "@/features/history/HistoryContext";
import { UndoRedoToolbar } from "@/features/history/UndoRedoToolbar";
import { ForceDirectedGraph } from "@/features/graph/ForceDirectedGraph";
import { BayesNetGraph } from "@/features/graph/BayesNetGraph";
import { GraphToolbar, type GraphView } from "@/features/graph/GraphToolbar";
import { deriveEdgesFromCliques } from "@/features/graph/deriveEdges";
import { buildNetworkExport, downloadJson } from "@/features/graph/networkExport";
import { JunctionTreePanel } from "@/features/graph/JunctionTreePanel";
import { DiscussionThread } from "@/features/market/DiscussionThread";
import { ResolveMarketPanel } from "@/features/market/ResolveMarketPanel";
import { EventTradePanel } from "@/features/trading/EventTradePanel";
import { CptPanel } from "@/features/trading/CptPanel";
import type { MarketEvent } from "@/lib/api/types";

export default function MarketDetail() {
  const { marketId } = useParams<{ marketId: string }>();
  const { session, isConfigured } = useSession();
  const { data, isLoading, error } = useMarket(marketId!);
  const events = useMarketEvents(marketId!);
  const accountRisk = useAccountRisk(session.accountId);

  // All hooks must run unconditionally (before the loading/error returns
  // below) so their order is stable across renders — see React error #310.

  // Track which market's CPT to display when a graph node is clicked.
  // null means "the market on this page".
  const [selectedMarketId, setSelectedMarketId] = useState<string | null>(null);
  const effectiveSelectedId = selectedMarketId ?? marketId!;
  const selectedMarketQuery = useMarket(effectiveSelectedId, {
    enabled: effectiveSelectedId !== marketId,
  });

  const handleNodeClick = useCallback((nodeId: string) => {
    setSelectedMarketId(nodeId);
  }, []);

  // Graph view toggle and toolbar state
  const [graphView, setGraphView] = useState<GraphView>("force");
  const queryClient = useQueryClient();
  const marketsQuery = useMarkets();
  const engineStatsQuery = useEngineStats(marketId!, { enabled: true });
  const allMarkets = marketsQuery.data?.markets ?? [];
  const cliques = engineStatsQuery.data?.cliques.cliques ?? [];

  const handleExport = useCallback(() => {
    const cliqueEdges = deriveEdgesFromCliques(cliques);
    const nodes = allMarkets.map((mk) => ({ id: mk.id, x: 0, y: 0 }));
    const data = buildNetworkExport(allMarkets, nodes, cliqueEdges, [], cliques);
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    downloadJson(data, `bayes-network-${ts}.json`);
  }, [allMarkets, cliques]);

  const handleImportSuccess = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.marketLists() });
  }, [queryClient]);

  if (isLoading) return <LoadingPage />;
  if (error) return <ErrorMessage message={error instanceof Error ? error.message : "Market not found"} />;
  if (!data) return null;

  const m = data.market;
  const selectedMarket =
    effectiveSelectedId === m.id ? m : selectedMarketQuery.data?.market ?? m;

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      <div>
        <div style={{ display: "flex", gap: "var(--space-md)", alignItems: "center", marginBottom: "var(--space-sm)" }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>{m.title}</h1>
          <StatusBadge status={m.status} />
        </div>
        <p style={{ color: "var(--color-text-muted)", marginBottom: "var(--space-md)" }}>{m.description}</p>
        <div style={{ display: "flex", gap: "var(--space-lg)", fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
          <span>Volume: {formatCurrency(m.volume)}</span>
          <span>Liquidity: {formatCurrency(m.liquidity)}</span>
          <span>Expires: {timeUntil(m.expires_at)}</span>
        </div>
      </div>

      <ProbabilityBar outcomes={m.outcomes} marginals={m.marginals} />

      <PositionCard marketId={m.id} accountRisk={accountRisk.data} isConfigured={isConfigured} />

      <ResolveMarketPanel market={m} />

      {m.status === "active" ? (
        <HistoryProvider>
          <AssumptionProvider>
            <UndoRedoToolbar />
            <AssumptionPanel market={m} />
            <CptPanel market={selectedMarket} />
            <EventTradePanel market={m} />
            <DiscussionThread market={m} />
            <GraphToolbar
              view={graphView}
              onViewChange={setGraphView}
              onExport={handleExport}
              onImportSuccess={handleImportSuccess}
            />
            {graphView === "force" ? (
              <ConnectedForceGraph focusMarketId={m.id} onNodeClick={handleNodeClick} />
            ) : (
              <BayesNetGraph focusMarketId={m.id} />
            )}
          </AssumptionProvider>
        </HistoryProvider>
      ) : (
        <>
          <CptPanel market={selectedMarket} />
          <EventTradePanel market={m} />
          <DiscussionThread market={m} />
          <GraphToolbar
            view={graphView}
            onViewChange={setGraphView}
            onExport={handleExport}
            onImportSuccess={handleImportSuccess}
          />
          {graphView === "force" ? (
            <ForceDirectedGraph focusMarketId={m.id} onNodeClick={handleNodeClick} />
          ) : (
            <BayesNetGraph focusMarketId={m.id} />
          )}
        </>
      )}

      {/* Event Journal */}
      <div>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>Event Journal</h2>
        {events.isLoading && <LoadingPage />}
        {events.data && events.data.events.length === 0 && (
          <span style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>No events yet.</span>
        )}
        {events.data && events.data.events.length > 0 && (
          <div style={{ borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflow: "hidden" }}>
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

      <JunctionTreePanel marketId={m.id} />
    </div>
  );
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
