import type { MarketAnalyticsTraderRow } from "@/lib/api/types";
import { formatCurrency } from "@/lib/utils/format";

export function TraderLeaderboard({ rows }: { rows: MarketAnalyticsTraderRow[] }) {
  return (
    <section style={cardStyle}>
      <div style={{ marginBottom: "var(--space-md)" }}>
        <h2 style={titleStyle}>Trader Leaderboard</h2>
        <p style={subtitleStyle}>
          Ranked directly from backend volume totals with deterministic tie-breaking.
        </p>
      </div>

      {rows.length === 0 ? (
        <div style={emptyStateStyle}>No accepted activity yet.</div>
      ) : (
        <div style={tableShellStyle}>
          <table
            data-testid="trader-leaderboard"
            style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}
          >
            <thead>
              <tr style={{ background: "var(--color-bg-hover)" }}>
                <th style={thStyle}>#</th>
                <th style={thStyle}>Trader</th>
                <th style={thStyle}>Trades</th>
                <th style={thStyle}>Volume</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={row.accountId} style={{ borderTop: "1px solid var(--color-border)" }}>
                  <td style={tdStyle}>{index + 1}</td>
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>
                    {row.accountId}
                  </td>
                  <td style={tdStyle}>{row.tradeCount}</td>
                  <td style={tdStyle}>{formatCurrency(row.volume)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
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
};

const tableShellStyle: React.CSSProperties = {
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  overflow: "hidden",
};

const emptyStateStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  fontSize: "0.84rem",
};

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  fontWeight: 600,
};

const tdStyle: React.CSSProperties = {
  padding: "8px 12px",
};
