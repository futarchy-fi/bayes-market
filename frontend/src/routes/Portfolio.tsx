import { useSession } from "@/features/session/context";
import { BayesApiError } from "@/lib/api/client";
import { useAccountExposure, useAccountRisk, useMarkets } from "@/lib/query/hooks";
import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { Link } from "react-router-dom";
import { formatProbability, formatRelativeTime } from "@/lib/utils/format";

function isAccountNotFoundError(error: unknown): boolean {
  return error instanceof BayesApiError
    && error.status === 404
    && error.code === "account_not_found";
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function formatSignedSize(value: number): string {
  if (value > 0) return `+${value.toFixed(2)}`;
  return value.toFixed(2);
}

export default function Portfolio() {
  const { session, isConfigured } = useSession();
  const exposureQuery = useAccountExposure(session.accountId);
  const riskQuery = useAccountRisk(session.accountId);
  const marketsQuery = useMarkets();
  const marketTitles = new Map(
    (marketsQuery.data?.markets ?? []).map((market): [string, string] => [market.id, market.title]),
  );

  if (!isConfigured) {
    return (
      <div style={{ textAlign: "center", padding: "var(--space-xl)", color: "var(--color-text-muted)" }}>
        Set your Account ID in the header to view your portfolio.
      </div>
    );
  }

  const exposure = exposureQuery.data?.account.exposure;
  const risk = riskQuery.data?.account.risk;
  const exposureMissing = isAccountNotFoundError(exposureQuery.error);
  const riskMissing = isAccountNotFoundError(riskQuery.error);
  const exposureError = exposureQuery.error && !exposureMissing ? exposureQuery.error : null;
  const riskError = riskQuery.error && !riskMissing ? riskQuery.error : null;
  const positions = [...(exposure?.positions ?? [])].sort(
    (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
  );

  if (!exposure && !risk && exposureQuery.isLoading && riskQuery.isLoading) {
    return <LoadingPage />;
  }

  if (!exposure && !risk && exposureMissing && riskMissing) {
    return <ErrorMessage message="Account not found or no positions yet." />;
  }

  if (!exposure && !risk && (exposureError || riskError)) {
    return (
      <ErrorMessage
        message={getErrorMessage(exposureError ?? riskError, "Unable to load portfolio.")}
      />
    );
  }

  const cap = risk?.capacityIndicators;
  const healthColor = cap?.status === "healthy" ? "var(--color-success)"
    : cap?.status === "warning" ? "var(--color-warning)"
    : "var(--color-danger)";

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Portfolio</h1>

      {risk && cap && (
        <div style={{ display: "grid", gap: "var(--space-sm)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "var(--space-md)" }}>
            <MetricCard label="Limit" value={cap.limit.toFixed(2)} />
            <MetricCard label="Available" value={cap.available.toFixed(2)} />
            <MetricCard label="Consumed" value={cap.consumed.toFixed(2)} />
            <MetricCard label="Utilization" value={`${(cap.utilization * 100).toFixed(1)}%`} />
            <MetricCard label="Health" value={cap.status} color={healthColor} />
            <MetricCard label="Min Asset (Overall)" value={risk.minAssets.overall.toFixed(2)} />
          </div>
          {risk.updatedAt && (
            <div style={{ fontSize: "0.7rem", color: "var(--color-text-muted)" }}>
              Last updated: {new Date(risk.updatedAt).toLocaleString()}
            </div>
          )}
        </div>
      )}

      {riskError && (
        <ErrorMessage message={getErrorMessage(riskError, "Unable to load risk metrics.")} />
      )}

      <div>
        <h2 style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>Live Outcome Holdings</h2>
        {exposureQuery.isLoading && !exposure ? (
          <span style={{ color: "var(--color-text-muted)" }}>Loading live holdings...</span>
        ) : exposureError ? (
          <ErrorMessage message={getErrorMessage(exposureError, "Unable to load live holdings.")} />
        ) : positions.length === 0 ? (
          <span style={{ color: "var(--color-text-muted)" }}>No live EventTrade positions.</span>
        ) : (
          <div style={{ borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
              <thead>
                <tr style={{ background: "var(--color-bg-hover)" }}>
                  <th style={thStyle}>Market</th>
                  <th style={thStyle}>Outcome</th>
                  <th style={thStyle}>Net Size</th>
                  <th style={thStyle}>Abs Size</th>
                  <th style={thStyle}>Last Price</th>
                  <th style={thStyle}>Updated</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((position) => (
                  <tr key={`${position.marketId}:${position.outcomeId}`} style={{ borderTop: "1px solid var(--color-border)" }}>
                    <td style={tdStyle}>
                      <Link to={`/markets/${position.marketId}`}>
                        {marketTitles.get(position.marketId) ?? position.marketId}
                      </Link>
                    </td>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{position.outcomeId}</td>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{formatSignedSize(position.netSize)}</td>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{position.absSize.toFixed(2)}</td>
                    <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{formatProbability(position.lastTradePrice)}</td>
                    <td style={tdStyle}>{formatRelativeTime(position.updatedAt)}</td>
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
