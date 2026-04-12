import { useState } from "react";
import { useAccountPnl } from "@/lib/query/hooks";
import { BayesApiError } from "@/lib/api/client";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import type { AccountPnlMarket } from "@/lib/api/types";

interface AccountPnLProps {
  accountId: string;
}

function pnlColor(value: number): string {
  if (value > 0) return "var(--color-success)";
  if (value < 0) return "var(--color-danger)";
  return "var(--color-text)";
}

function formatPnl(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

export function AccountPnL({ accountId }: AccountPnLProps) {
  const { data, isLoading, error } = useAccountPnl(accountId);

  if (!accountId) return null;

  const isNotFound = error instanceof BayesApiError
    && (error.status === 404 || error.code === "no_orders_found");

  if (isLoading) return <LoadingPage />;

  if (isNotFound) {
    return (
      <div style={sectionStyle}>
        <h2 style={headingStyle}>Account P&L</h2>
        <div style={placeholderStyle}>No trades yet</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={sectionStyle}>
        <h2 style={headingStyle}>Account P&L</h2>
        <ErrorMessage message={error instanceof Error ? error.message : "Failed to load account P&L"} />
      </div>
    );
  }

  if (!data) return null;

  const { markets, summary } = data.pnl;

  return (
    <div style={sectionStyle}>
      <h2 style={headingStyle}>Account P&L</h2>

      <div style={summaryBarStyle}>
        <SummaryMetric label="Cost Basis" value={summary.totalCostBasis} />
        <SummaryMetric label="Current Value" value={summary.totalCurrentValue} />
        <SummaryMetric label="Unrealized" value={summary.totalUnrealizedPnl} colored />
        <SummaryMetric label="Realized" value={summary.totalRealizedPnl} colored />
        <SummaryMetric label="Total P&L" value={summary.totalPnl} colored />
      </div>

      {markets.map((market) => (
        <MarketPnlRow key={market.marketId} market={market} />
      ))}
    </div>
  );
}

function SummaryMetric({ label, value, colored }: { label: string; value: number; colored?: boolean }) {
  return (
    <div style={metricBoxStyle}>
      <div style={metricLabelStyle}>{label}</div>
      <div style={{
        fontSize: "1.1rem",
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        color: colored ? pnlColor(value) : "var(--color-text)",
      }}>
        {formatPnl(value)}
      </div>
    </div>
  );
}

function MarketPnlRow({ market }: { market: AccountPnlMarket }) {
  const [expanded, setExpanded] = useState(false);
  const outcomeEntries = Object.entries(market.outcomes);

  return (
    <div style={marketRowStyle}>
      <button onClick={() => setExpanded(!expanded)} style={marketToggleStyle}>
        <span style={{ fontSize: "0.65rem", marginRight: 6 }}>
          {expanded ? "\u25BC" : "\u25B6"}
        </span>
        <span style={{ flex: 1 }}>{market.marketId}</span>
        <span style={{
          fontFamily: "var(--font-mono)",
          fontWeight: 600,
          color: pnlColor(market.summary.totalPnl),
        }}>
          {formatPnl(market.summary.totalPnl)}
        </span>
      </button>

      {expanded && (
        <div style={{ overflow: "hidden" }}>
          <table style={tableStyle}>
            <thead>
              <tr style={{ background: "var(--color-bg-hover)" }}>
                <th style={thStyle}>Outcome</th>
                <th style={thStyle}>Net Size</th>
                <th style={thStyle}>Cost Basis</th>
                <th style={thStyle}>Current Value</th>
                <th style={thStyle}>Unrealized</th>
                <th style={thStyle}>Total P&L</th>
              </tr>
            </thead>
            <tbody>
              {outcomeEntries.map(([id, pnl]) => (
                <tr key={id} style={{ borderTop: "1px solid var(--color-border)" }}>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{id}</td>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{pnl.netSize.toFixed(2)}</td>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{pnl.costBasis.toFixed(2)}</td>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{pnl.currentValue.toFixed(2)}</td>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", color: pnlColor(pnl.unrealizedPnl) }}>
                    {formatPnl(pnl.unrealizedPnl)}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", color: pnlColor(pnl.totalPnl) }}>
                    {formatPnl(pnl.totalPnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const sectionStyle: React.CSSProperties = {
  padding: "var(--space-sm) var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const headingStyle: React.CSSProperties = {
  fontSize: "1.1rem",
  fontWeight: 600,
  marginBottom: "var(--space-sm)",
};

const placeholderStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  fontSize: "0.85rem",
};

const summaryBarStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))",
  gap: "var(--space-sm)",
  marginBottom: "var(--space-md)",
};

const metricBoxStyle: React.CSSProperties = {
  padding: "var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-bg-hover)",
};

const metricLabelStyle: React.CSSProperties = {
  fontSize: "0.7rem",
  color: "var(--color-text-muted)",
  marginBottom: "var(--space-xs)",
};

const marketRowStyle: React.CSSProperties = {
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  marginBottom: "var(--space-xs)",
  overflow: "hidden",
};

const marketToggleStyle: React.CSSProperties = {
  width: "100%",
  display: "flex",
  alignItems: "center",
  gap: "var(--space-sm)",
  padding: "var(--space-sm) var(--space-md)",
  background: "none",
  border: "none",
  color: "var(--color-text)",
  cursor: "pointer",
  fontSize: "0.85rem",
  textAlign: "left",
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: "0.8rem",
};

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "6px 12px",
  fontWeight: 500,
};

const tdStyle: React.CSSProperties = {
  padding: "6px 12px",
};
