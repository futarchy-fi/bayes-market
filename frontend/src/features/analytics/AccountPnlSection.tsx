import { StatusBadge } from "@/components/ui/StatusBadge";
import { ErrorMessage, LoadingPage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import type { AccountPnlResponse } from "@/lib/api/types";
import { formatCurrency } from "@/lib/utils/format";
import { formatSignedCurrency } from "./chartUtils";

interface AccountPnlSectionProps {
  accountId: string;
  selectedMarketId: string;
  data?: AccountPnlResponse;
  isLoading: boolean;
  error: unknown;
}

export function AccountPnlSection({
  accountId,
  selectedMarketId,
  data,
  isLoading,
  error,
}: AccountPnlSectionProps) {
  return (
    <section style={cardStyle}>
      <div style={{ marginBottom: "var(--space-md)" }}>
        <h2 style={titleStyle}>Account P&amp;L</h2>
        <p style={subtitleStyle}>Account-wide mark-to-market. Freshness can move when any market you hold reprices, even without a new trade from you.</p>
      </div>

      {!accountId && (
        <div style={emptyStateStyle}>
          Set your Account ID in the header to load mark-to-market P&amp;L.
        </div>
      )}

      {accountId && isLoading && <LoadingPage />}

      {accountId && !isLoading && !!error && !data && (
        <ErrorMessage message="Unable to load account P&L right now. Market analytics is still available." />
      )}

      {accountId && !isLoading && data && (
        <>
          {error && <ReconnectingHint />}
          <AccountPnlContent data={data} selectedMarketId={selectedMarketId} />
        </>
      )}
    </section>
  );
}

function AccountPnlContent({
  data,
  selectedMarketId,
}: {
  data: AccountPnlResponse;
  selectedMarketId: string;
}) {
  const { pnl } = data.account;
  const selectedMarketPosition = pnl.positions.find((position) => position.marketId === selectedMarketId);

  return (
    <div style={{ display: "grid", gap: "var(--space-md)" }}>
      <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
        <PnlMetricCard label="Cost Basis" value={formatCurrency(pnl.totals.costBasis)} />
        <PnlMetricCard label="Marked Value" value={formatCurrency(pnl.totals.markedValue)} />
        <PnlMetricCard label="Realized P&L" value={formatSignedCurrency(pnl.totals.realizedPnl)} accent={toneForValue(pnl.totals.realizedPnl)} />
        <PnlMetricCard label="Unrealized P&L" value={formatSignedCurrency(pnl.totals.unrealizedPnl)} accent={toneForValue(pnl.totals.unrealizedPnl)} />
        <PnlMetricCard label="Net P&L" value={formatSignedCurrency(pnl.totals.netPnl)} accent={toneForValue(pnl.totals.netPnl)} />
      </div>

      <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
        Mark-to-market updated: {new Date(pnl.updatedAt).toLocaleString()}
      </div>

      {selectedMarketPosition ? (
        <div style={selectedMarketCardStyle}>
          <div style={{ display: "flex", gap: "var(--space-sm)", alignItems: "center", flexWrap: "wrap", marginBottom: "var(--space-sm)" }}>
            <div style={{ fontSize: "0.9rem", fontWeight: 600 }}>{selectedMarketPosition.marketTitle}</div>
            <StatusBadge status={selectedMarketPosition.marketStatus} />
          </div>
          <div style={{ display: "grid", gap: "var(--space-sm)", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
            <SelectedMetric label="Cost Basis" value={formatCurrency(selectedMarketPosition.costBasis)} />
            <SelectedMetric label="Marked Value" value={formatCurrency(selectedMarketPosition.markedValue)} />
            <SelectedMetric label="Realized" value={formatSignedCurrency(selectedMarketPosition.realizedPnl)} tone={toneForValue(selectedMarketPosition.realizedPnl)} />
            <SelectedMetric label="Unrealized" value={formatSignedCurrency(selectedMarketPosition.unrealizedPnl)} tone={toneForValue(selectedMarketPosition.unrealizedPnl)} />
          </div>
        </div>
      ) : (
        <div style={emptyStateStyle}>
          No recorded exposure in the selected market yet.
        </div>
      )}

      {pnl.positions.length > 0 ? (
        <div style={tableShellStyle}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
            <thead>
              <tr style={{ background: "var(--color-bg-hover)" }}>
                <th style={thStyle}>Market</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Cost Basis</th>
                <th style={thStyle}>Marked Value</th>
                <th style={thStyle}>Realized</th>
                <th style={thStyle}>Unrealized</th>
              </tr>
            </thead>
            <tbody>
              {pnl.positions.map((position) => {
                const highlighted = position.marketId === selectedMarketId;
                return (
                  <tr
                    key={position.marketId}
                    style={{
                      borderTop: "1px solid var(--color-border)",
                      background: highlighted ? "rgba(99, 102, 241, 0.12)" : "transparent",
                    }}
                  >
                    <td style={tdStyle}>{position.marketTitle}</td>
                    <td style={tdStyle}>
                      <StatusBadge status={position.marketStatus} />
                    </td>
                    <td style={tdStyle}>{formatCurrency(position.costBasis)}</td>
                    <td style={tdStyle}>{formatCurrency(position.markedValue)}</td>
                    <td style={{ ...tdStyle, color: toneForValue(position.realizedPnl) }}>{formatSignedCurrency(position.realizedPnl)}</td>
                    <td style={{ ...tdStyle, color: toneForValue(position.unrealizedPnl) }}>{formatSignedCurrency(position.unrealizedPnl)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={emptyStateStyle}>No marked positions yet.</div>
      )}
    </div>
  );
}

function PnlMetricCard({
  label,
  value,
  accent = "var(--color-text)",
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div style={metricCardStyle}>
      <div style={metricLabelStyle}>{label}</div>
      <div style={{ ...metricValueStyle, color: accent }}>{value}</div>
    </div>
  );
}

function SelectedMetric({
  label,
  value,
  tone = "var(--color-text)",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div>
      <div style={metricLabelStyle}>{label}</div>
      <div style={{ ...metricValueStyle, fontSize: "1rem", color: tone }}>{value}</div>
    </div>
  );
}

function toneForValue(value: number): string {
  if (value > 0) {
    return "var(--color-success)";
  }

  if (value < 0) {
    return "var(--color-danger)";
  }

  return "var(--color-text)";
}

const cardStyle: React.CSSProperties = {
  padding: "var(--space-lg)",
  borderRadius: "var(--radius-lg)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const titleStyle: React.CSSProperties = {
  fontSize: "1.05rem",
  fontWeight: 600,
};

const subtitleStyle: React.CSSProperties = {
  marginTop: "var(--space-xs)",
  fontSize: "0.8rem",
  color: "var(--color-text-muted)",
  maxWidth: 640,
};

const emptyStateStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  fontSize: "0.84rem",
};

const metricCardStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
};

const metricLabelStyle: React.CSSProperties = {
  fontSize: "0.72rem",
  fontWeight: 700,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--color-text-muted)",
  marginBottom: "var(--space-xs)",
};

const metricValueStyle: React.CSSProperties = {
  fontSize: "1.1rem",
  fontWeight: 700,
};

const selectedMarketCardStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid rgba(99, 102, 241, 0.4)",
  background: "rgba(99, 102, 241, 0.1)",
};

const tableShellStyle: React.CSSProperties = {
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  overflow: "hidden",
};

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  fontWeight: 600,
};

const tdStyle: React.CSSProperties = {
  padding: "8px 12px",
};
