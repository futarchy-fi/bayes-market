import { Outlet, NavLink } from "react-router-dom";
import { useSession } from "@/features/session/context";

export function AppLayout() {
  const { session, setAccountId, setAgentId } = useSession();

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <header style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-lg)",
        padding: "var(--space-sm) var(--space-lg)",
        borderBottom: "1px solid var(--color-border)",
        background: "var(--color-bg-surface)",
      }}>
        <span style={{ fontWeight: 700, fontSize: "1.1rem" }}>Bayes Market</span>
        <nav style={{ display: "flex", gap: "var(--space-md)" }}>
          <NavLink to="/markets" style={navLinkStyle}>Markets</NavLink>
          <NavLink to="/portfolio" style={navLinkStyle}>Portfolio</NavLink>
          <NavLink to="/system" style={navLinkStyle}>System</NavLink>
        </nav>
        <div style={{ marginLeft: "auto", display: "flex", gap: "var(--space-sm)", alignItems: "center" }}>
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
        </div>
      </header>
      <main style={{ flex: 1, padding: "var(--space-lg)", maxWidth: 1200, margin: "0 auto", width: "100%" }}>
        <Outlet />
      </main>
    </div>
  );
}

const navLinkStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
  fontSize: "0.875rem",
  fontWeight: isActive ? 600 : 400,
  color: isActive ? "var(--color-primary)" : "var(--color-text-muted)",
  textDecoration: "none",
});

const headerInputStyle: React.CSSProperties = {
  padding: "4px 8px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.8rem",
  width: 160,
};
