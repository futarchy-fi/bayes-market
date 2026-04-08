import { useSession } from "@/features/session/context";
import { useAccountRisk } from "@/lib/query/hooks";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { Link } from "react-router-dom";

export default function Portfolio() {
  const { session, isConfigured } = useSession();
  const { data, isLoading, error } = useAccountRisk(session.accountId);

  if (!isConfigured) {
    return (
      <div style={{ textAlign: "center", padding: "var(--space-xl)", color: "var(--color-text-muted)" }}>
        Set your Account ID in the header to view your portfolio.
      </div>
    );
  }

  if (isLoading) return <LoadingPage />;
  if (error) return <ErrorMessage message="Account not found or no positions yet." />;
  if (!data) return null;

  const risk = data.account.risk;
  const cap = risk.capacityIndicators;
  const healthColor = cap.status === "healthy" ? "var(--color-success)"
    : cap.status === "warning" ? "var(--color-warning)"
    : "var(--color-danger)";

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Portfolio</h1>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "var(--space-md)" }}>
        <MetricCard label="Available" value={cap.available.toFixed(2)} />
        <MetricCard label="Consumed" value={cap.consumed.toFixed(2)} />
        <MetricCard label="Utilization" value={`${(cap.utilization * 100).toFixed(1)}%`} />
        <MetricCard label="Health" value={cap.status} color={healthColor} />
      </div>

      <div>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>Per-Market Positions</h2>
        {risk.minAssets.markets.length === 0 ? (
          <span style={{ color: "var(--color-text-muted)" }}>No positions.</span>
        ) : (
          <div style={{ borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
              <thead>
                <tr style={{ background: "var(--color-bg-hover)" }}>
                  <th style={thStyle}>Market</th>
                  <th style={thStyle}>Min Asset</th>
                  <th style={thStyle}>Utilization</th>
                  <th style={thStyle}>Trades</th>
                </tr>
              </thead>
              <tbody>
                {risk.minAssets.markets.map((mr) => (
                  <tr key={mr.marketId} style={{ borderTop: "1px solid var(--color-border)" }}>
                    <td style={tdStyle}>
                      <Link to={`/markets/${mr.marketId}`}>{mr.marketId}</Link>
                    </td>
                    <td style={tdStyle}>{mr.minAsset.toFixed(2)}</td>
                    <td style={tdStyle}>{(mr.utilization * 100).toFixed(1)}%</td>
                    <td style={tdStyle}>{mr.commandCount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      padding: "var(--space-md)",
      borderRadius: "var(--radius-md)",
      background: "var(--color-bg-surface)",
      border: "1px solid var(--color-border)",
    }}>
      <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-xs)" }}>{label}</div>
      <div style={{ fontSize: "1.25rem", fontWeight: 600, color: color ?? "var(--color-text)" }}>{value}</div>
    </div>
  );
}

const thStyle: React.CSSProperties = { textAlign: "left", padding: "6px 12px", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "6px 12px" };
