import { LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import { useLeaderboard } from "@/lib/exchange/hooks";

export default function Leaderboard() {
  const leaderboard = useLeaderboard();
  if (leaderboard.isLoading) return <LoadingPage />;
  if (leaderboard.error && !leaderboard.data) return <ErrorMessage message="Could not load the credits leaderboard." />;

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      {leaderboard.error && <ReconnectingHint />}
      <div>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Credits leaderboard</h1>
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>Top exchange accounts by total credits.</p>
      </div>
      <div style={{ borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead><tr style={{ background: "var(--color-bg-hover)" }}><th style={thStyle}>Rank</th><th style={thStyle}>Trader</th><th style={thStyle}>Total credits</th></tr></thead>
          <tbody>{leaderboard.data?.entries.map((entry, index) => (
            <tr key={entry.accountId} style={{ borderTop: "1px solid var(--color-border)" }}>
              <td style={tdStyle}>{index + 1}</td>
              <td style={tdStyle}>{entry.login ? `@${entry.login}` : `Account #${entry.accountId}`}</td>
              <td style={{ ...tdStyle, fontFamily: "var(--font-mono)" }}>{entry.total}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = { textAlign: "left", padding: "8px 12px", fontWeight: 500 };
const tdStyle: React.CSSProperties = { padding: "8px 12px" };
