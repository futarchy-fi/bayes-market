import { Outlet, NavLink, useLocation } from "react-router-dom";
import { useSession } from "@/features/session/context";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { useExchangeMe } from "@/lib/exchange/hooks";
import { GithubSignInLink, useExchangeSession } from "@/lib/exchange/session";
import { isExchangeMode } from "@/lib/exchangeMode";
import { formatCredits } from "@/lib/utils/format";

export function AppLayout() {
  const { session, setAccountId, setAgentId } = useSession();
  const exchange = useExchangeSession();
  const me = useExchangeMe();
  const exchangeMode = isExchangeMode();
  const location = useLocation();
  const showHeaderNotice = Boolean(exchange.sessionNotice && location.pathname !== "/portfolio");

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", minWidth: 0 }}>
      <header className="app-header">
        <div className="app-brand">
          <NavLink
            to="/"
            style={{ fontWeight: 700, fontSize: "1.1rem", color: "var(--color-text)", textDecoration: "none", whiteSpace: "nowrap" }}
          >
            Bayes Market
          </NavLink>
          {!exchangeMode && <span style={exchangeBadgeStyle}>paper mode</span>}
        </div>
        <nav className="app-nav" aria-label="Primary navigation">
          <NavLink to="/" end style={navLinkStyle}>Network</NavLink>
          <NavLink to="/markets" style={navLinkStyle}>Markets</NavLink>
          <NavLink to="/portfolio" style={navLinkStyle}>Portfolio</NavLink>
          <NavLink to="/leaderboard" style={navLinkStyle}>Leaderboard</NavLink>
          <NavLink to="/system" style={navLinkStyle}>System</NavLink>
        </nav>
        <div className="app-auth">
          {!exchangeMode && (
            <>
              <input
                placeholder="Account ID"
                value={session.accountId}
                onChange={(e) => setAccountId(e.target.value)}
                style={headerInputStyle}
              />
              <input
                placeholder="Agent ID (optional)"
                value={session.agentId}
                onChange={(e) => setAgentId(e.target.value)}
                style={{ ...headerInputStyle, width: 140 }}
              />
            </>
          )}
          {exchange.isSignedIn ? (
            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-xs)", fontSize: "0.8rem", flexWrap: "wrap" }}>
              <span>@{exchange.session.githubLogin || `account ${me.data?.account_id ?? ""}`}</span>
              {me.data && <span style={creditChipStyle}>{formatCredits(me.data.available)} credits</span>}
              <button type="button" onClick={exchange.signOut} style={signOutStyle}>Sign out</button>
            </div>
          ) : (
            <GithubSignInLink style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>
              Sign in with GitHub
            </GithubSignInLink>
          )}
        </div>
      </header>
      {showHeaderNotice && (
        <div role="status" style={sessionNoticeBannerStyle}>
          <span>{exchange.sessionNotice}</span>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
            <GithubSignInLink style={{ fontWeight: 600, fontSize: "0.78rem" }}>
              Sign in with GitHub
            </GithubSignInLink>
            <button
              type="button"
              onClick={exchange.clearSessionNotice}
              aria-label="Dismiss notice"
              style={dismissNoticeStyle}
            >
              ×
            </button>
          </div>
        </div>
      )}
      <main className="app-main">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}

const navLinkStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
  fontSize: "0.875rem",
  fontWeight: isActive ? 600 : 400,
  color: isActive ? "var(--color-primary)" : "var(--color-text-muted)",
  textDecoration: "none",
  whiteSpace: "nowrap",
});

const headerInputStyle: React.CSSProperties = {
  padding: "4px 8px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.8rem",
  width: 160,
  maxWidth: "100%",
};

const creditChipStyle: React.CSSProperties = { padding: "2px 7px", borderRadius: 999, background: "var(--color-bg-hover)", color: "var(--color-success)", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" };
const signOutStyle: React.CSSProperties = { padding: 0, border: 0, background: "transparent", color: "var(--color-text-muted)", cursor: "pointer", fontSize: "0.7rem" };
const exchangeBadgeStyle: React.CSSProperties = { padding: "2px 8px", borderRadius: 999, background: "var(--color-primary)", color: "#fff", fontSize: "0.7rem", fontWeight: 600, whiteSpace: "nowrap" };
const sessionNoticeBannerStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  padding: "8px var(--space-lg)",
  borderBottom: "1px solid var(--color-warning)",
  background: "rgba(234, 179, 8, 0.12)",
  color: "var(--color-text)",
  fontSize: "0.8rem",
};
const dismissNoticeStyle: React.CSSProperties = {
  padding: "0 4px",
  border: 0,
  background: "transparent",
  color: "var(--color-text-muted)",
  cursor: "pointer",
  fontSize: "1rem",
  lineHeight: 1,
};
