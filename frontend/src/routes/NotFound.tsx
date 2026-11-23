import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div style={wrapStyle}>
      <div style={codeStyle}>404</div>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "var(--space-xs)" }}>
        Page not found
      </h1>
      <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem", maxWidth: 420, marginBottom: "var(--space-lg)" }}>
        The page you requested does not exist or may have moved.
      </p>
      <div style={{ display: "flex", gap: "var(--space-sm)", justifyContent: "center", flexWrap: "wrap" }}>
        <Link to="/" style={primaryBtnStyle}>
          Back to Network
        </Link>
        <Link to="/markets" style={secondaryBtnStyle}>
          Browse Markets
        </Link>
      </div>
    </div>
  );
}

const wrapStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  textAlign: "center",
  padding: "48px 24px",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
  maxWidth: 540,
  margin: "24px auto",
};

const codeStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "0.8rem",
  fontWeight: 700,
  color: "var(--color-primary)",
  padding: "2px 10px",
  borderRadius: 999,
  background: "rgba(99, 102, 241, 0.14)",
  marginBottom: "var(--space-sm)",
};

const primaryBtnStyle: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-primary)",
  color: "#fff",
  fontSize: "0.875rem",
  fontWeight: 600,
  textDecoration: "none",
};

const secondaryBtnStyle: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.875rem",
  fontWeight: 500,
  textDecoration: "none",
};
