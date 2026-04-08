import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={containerStyle}>
          <div style={cardStyle}>
            <div style={{ fontSize: "1.1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>
              Something went wrong
            </div>
            <pre style={errorStyle}>{this.state.error.message}</pre>
            <button
              onClick={() => this.setState({ error: null })}
              style={retryStyle}
            >
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const containerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "center",
  alignItems: "center",
  padding: "var(--space-xl)",
};

const cardStyle: React.CSSProperties = {
  padding: "var(--space-lg)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-danger)",
  background: "rgba(239, 68, 68, 0.05)",
  maxWidth: 500,
  textAlign: "center",
};

const errorStyle: React.CSSProperties = {
  margin: 0,
  padding: "var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-bg)",
  border: "1px solid var(--color-border)",
  fontSize: "0.8rem",
  fontFamily: "var(--font-mono)",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  textAlign: "left",
  marginBottom: "var(--space-md)",
};

const retryStyle: React.CSSProperties = {
  padding: "8px 20px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
  color: "var(--color-text)",
  fontSize: "0.85rem",
  cursor: "pointer",
};
