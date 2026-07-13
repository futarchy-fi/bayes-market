import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useSession } from "@/features/session/context";
import { useAccountRisk, useMarkets } from "@/lib/query/hooks";
import { useExchangeMe, useMeNet } from "@/lib/exchange/hooks";
import { useExchangeSession } from "@/lib/exchange/session";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";

export default function Portfolio() {
  const { session, isConfigured } = useSession();
  const riskQuery = useAccountRisk(session.accountId);
  const marketsQuery = useMarkets();
  const { isSignedIn } = useExchangeSession();
  const exchangeMe = useExchangeMe();
  const net = useMeNet();
  const marketTitles = useMemo(() => new Map(marketsQuery.data?.markets.map((market) => [market.id, market.title]) ?? []), [marketsQuery.data]);

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Portfolio</h1>
      {isSignedIn && <ExchangePortfolio me={exchangeMe} net={net} />}
      <PaperPortfolio isConfigured={isConfigured} riskQuery={riskQuery} marketTitles={marketTitles} />
    </div>
  );
}

function ExchangePortfolio({ me, net }: {
  me: ReturnType<typeof useExchangeMe>;
  net: ReturnType<typeof useMeNet>;
}) {
  if (me.isLoading || net.isLoading) return <LoadingPage />;
  if (me.error || net.error) return <ErrorMessage message="Could not load your credits exchange portfolio." />;

  return (
    <section style={{ display: "grid", gap: "var(--space-md)" }}>
      <h2 style={sectionTitle}>Exchange (credits)</h2>
      <div style={metricGridStyle}>
        <MetricCard label="Available" value={me.data?.available ?? "—"} />
        <MetricCard label="Frozen" value={me.data?.frozen ?? "—"} />
        <MetricCard label="Open stake" value={net.data?.openStake ?? "—"} />
        <MetricCard label="Settled P&L" value={net.data?.settledPnl ?? "—"} />
      </div>
      {(net.data?.orders.length ?? 0) === 0 ? (
        <span style={{ color: "var(--color-text-muted)" }}>No credits orders.</span>
      ) : (
        <div style={tableWrapStyle}>
          <table style={tableStyle}>
            <thead><tr style={{ background: "var(--color-bg-hover)" }}><th style={thStyle}>Order</th><th style={thStyle}>Variable</th><th style={thStyle}>Outcome</th><th style={thStyle}>Target</th><th style={thStyle}>Stake</th><th style={thStyle}>Status</th></tr></thead>
            <tbody>{net.data?.orders.map((order) => (
              <tr key={order.orderId} style={{ borderTop: "1px solid var(--color-border)" }}>
                <td style={tdStyle}>{order.orderId}</td><td style={tdStyle}>{order.variableId}</td><td style={tdStyle}>{order.outcomeId}</td><td style={tdStyle}>{(order.target * 100).toFixed(1)}%</td><td style={tdStyle}>{order.stake}</td><td style={tdStyle}>{order.status}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PaperPortfolio({ isConfigured, riskQuery, marketTitles }: {
  isConfigured: boolean;
  riskQuery: ReturnType<typeof useAccountRisk>;
  marketTitles: Map<string, string>;
}) {
  if (!isConfigured) return <div style={promptStyle}>Set your Account ID in the header to view your paper portfolio.</div>;
  if (riskQuery.isLoading) return <LoadingPage />;
  if (riskQuery.error) return <ErrorMessage message="Account not found or no positions yet." />;
  if (!riskQuery.data) return null;

  const risk = riskQuery.data.account.risk;
  const cap = risk.capacityIndicators;
  const healthColor = cap.status === "healthy" ? "var(--color-success)" : cap.status === "warning" ? "var(--color-warning)" : "var(--color-danger)";
  return (
    <section style={{ display: "grid", gap: "var(--space-md)" }}>
      <h2 style={sectionTitle}>Paper belief flow</h2>
      <div style={metricGridStyle}>
        <MetricCard label="Limit" value={cap.limit.toFixed(2)} />
        <MetricCard label="Available" value={cap.available.toFixed(2)} />
        <MetricCard label="Consumed" value={cap.consumed.toFixed(2)} />
        <MetricCard label="Utilization" value={`${(cap.utilization * 100).toFixed(1)}%`} />
        <MetricCard label="Health" value={cap.status} color={healthColor} />
        <MetricCard label="Min Asset (Overall)" value={risk.minAssets.overall.toFixed(2)} />
      </div>
      {risk.updatedAt && <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>Last updated: {new Date(risk.updatedAt).toLocaleString()}</div>}
      <div>
        <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>Per-Market Positions</h3>
        {risk.minAssets.markets.length === 0 ? <span style={{ color: "var(--color-text-muted)" }}>No positions.</span> : (
          <div style={tableWrapStyle}><table style={tableStyle}>
            <thead><tr style={{ background: "var(--color-bg-hover)" }}><th style={thStyle}>Market</th><th style={thStyle}>Min Asset</th><th style={thStyle}>Utilization</th><th style={thStyle}>Trades</th></tr></thead>
            <tbody>{risk.minAssets.markets.map((market) => (
              <tr key={market.marketId} style={{ borderTop: "1px solid var(--color-border)" }}><td style={tdStyle}><Link to={`/markets/${market.marketId}`}>{marketTitles.get(market.marketId) ?? market.marketId}</Link></td><td style={tdStyle}>{market.minAsset.toFixed(2)}</td><td style={tdStyle}>{(market.utilization * 100).toFixed(1)}%</td><td style={tdStyle}>{market.commandCount}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
    </section>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return <div style={{ padding: "var(--space-md)", borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", background: "var(--color-bg-surface)" }}><div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-xs)" }}>{label}</div><div style={{ fontSize: "1.25rem", fontWeight: 600, color: color ?? "var(--color-text)" }}>{value}</div></div>;
}

const sectionTitle: React.CSSProperties = { fontSize: "1.1rem", fontWeight: 600 };
const metricGridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "var(--space-md)" };
const promptStyle: React.CSSProperties = { textAlign: "center", padding: "var(--space-xl)", color: "var(--color-text-muted)" };
const tableWrapStyle: React.CSSProperties = { borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflow: "auto" };
const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" };
const thStyle: React.CSSProperties = { textAlign: "left", padding: "6px 12px", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "6px 12px" };
