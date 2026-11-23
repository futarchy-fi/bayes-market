import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import { useLeaderboard } from "@/lib/exchange/hooks";
import type { LeaderboardEntry } from "@/lib/exchange/client";
import { formatCredits } from "@/lib/utils/format";

export default function Leaderboard() {
  const leaderboard = useLeaderboard();
  if (leaderboard.isLoading) return <LoadingPage />;
  if (leaderboard.error && !leaderboard.data) return <ErrorMessage message="Could not load the credits leaderboard." />;

  const entries = leaderboard.data?.entries ?? [];
  const showTrades = entries.some((entry) => entry.netOrders !== undefined);
  const showVolume = entries.some((entry) => entry.netVolume !== undefined);

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)", minWidth: 0 }}>
      {leaderboard.error && <ReconnectingHint />}
      <div>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Credits leaderboard</h1>
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>Top exchange accounts by total credits.</p>
      </div>
      <div style={{ borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr style={{ background: "var(--color-bg-hover)" }}>
              <th style={thStyle}>Rank</th>
              <th style={thStyle}>Trader</th>
              {showTrades && <th style={{ ...thStyle, textAlign: "right" }}>Trades</th>}
              {showVolume && <th style={{ ...thStyle, textAlign: "right" }}>Volume</th>}
              <th style={{ ...thStyle, textAlign: "right" }}>Total credits</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr key={entry.accountId} style={{ borderTop: "1px solid var(--color-border)" }}>
                <td style={{ ...tdStyle, fontVariantNumeric: "tabular-nums" }}>{index + 1}</td>
                <td style={tdStyle}>
                  <TraderIdentity entry={entry} />
                </td>
                {showTrades && (
                  <td style={{ ...tdStyle, ...numericCellStyle }}>
                    {entry.netOrders !== undefined ? entry.netOrders.toLocaleString() : "—"}
                  </td>
                )}
                {showVolume && (
                  <td style={{ ...tdStyle, ...numericCellStyle }}>
                    {entry.netVolume !== undefined ? formatCredits(entry.netVolume) : "—"}
                  </td>
                )}
                <td style={{ ...tdStyle, ...numericCellStyle }}>
                  {formatCredits(entry.total)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TraderIdentity({ entry }: { entry: LeaderboardEntry }) {
  const displayName = entry.displayName?.trim();
  if (displayName) {
    return (
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: "2px 8px" }}>
        <span style={{ fontWeight: 600, color: "var(--color-text)" }}>{displayName}</span>
        <span style={{ fontSize: "0.78rem", color: "var(--color-text-muted)" }}>
          {entry.login ? `@${entry.login}` : `Account #${entry.accountId}`}
        </span>
      </div>
    );
  }
  return <>{entry.login ? `@${entry.login}` : `Account #${entry.accountId}`}</>;
}

const thStyle: React.CSSProperties = { textAlign: "left", padding: "8px 12px", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "8px 12px" };
const numericCellStyle: React.CSSProperties = {
  textAlign: "right",
  fontFamily: "var(--font-mono)",
  fontVariantNumeric: "tabular-nums",
};
