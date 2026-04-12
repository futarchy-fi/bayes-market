import { useMarketPnl } from "@/lib/query/hooks";
import { BayesApiError } from "@/lib/api/client";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";

interface PnLSummaryProps {
  marketId: string;
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

export function PnLSummary({ marketId, accountId }: PnLSummaryProps) {
  const { data, isLoading, error } = useMarketPnl(marketId, accountId);

  if (!accountId) return null;

  const isNotFound = error instanceof BayesApiError
    && (error.status === 404 || error.code === "no_orders_found");

  if (isLoading) return <LoadingPage />;

  if (isNotFound) {
    return (
      <div style={sectionStyle}>
        <h2 style={headingStyle}>P&L Summary</h2>
        <div style={placeholderStyle}>No trades yet</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={sectionStyle}>
        <h2 style={headingStyle}>P&L Summary</h2>
        <ErrorMessage message={error instanceof Error ? error.message : "Failed to load P&L"} />
      </div>
    );
  }

  if (!data) return null;

  const { outcomes, summary } = data.pnl;
  const outcomeEntries = Object.entries(outcomes);

  return (
    <div style={sectionStyle}>
      <h2 style={headingStyle}>P&L Summary</h2>
      <div style={tableWrapperStyle}>
        <table style={tableStyle}>
          <thead>
            <tr style={{ background: "var(--color-bg-hover)" }}>
              <th style={thStyle}>Outcome</th>
              <th style={thStyle}>Net Size</th>
              <th style={thStyle}>Cost Basis</th>
              <th style={thStyle}>Current Value</th>
              <th style={thStyle}>Unrealized P&L</th>
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
            <tr style={{ borderTop: "2px solid var(--color-border)", fontWeight: 600 }}>
              <td style={tdStyle}>Total</td>
              <td style={tdStyle} />
              <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{summary.totalCostBasis.toFixed(2)}</td>
              <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{summary.totalCurrentValue.toFixed(2)}</td>
              <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", color: pnlColor(summary.totalUnrealizedPnl) }}>
                {formatPnl(summary.totalUnrealizedPnl)}
              </td>
              <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", color: pnlColor(summary.totalPnl) }}>
                {formatPnl(summary.totalPnl)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
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

const tableWrapperStyle: React.CSSProperties = {
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  overflow: "hidden",
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
