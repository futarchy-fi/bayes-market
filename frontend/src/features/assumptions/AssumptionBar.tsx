import { useAssumptions } from "./AssumptionContext";

export function AssumptionBar() {
  const { assumptions, removeAssumption, clearAll } = useAssumptions();

  if (assumptions.length === 0) return null;

  return (
    <div style={barStyle}>
      <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)", marginRight: 8 }}>
        GIVEN:
      </span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, flex: 1 }}>
        {assumptions.map((a) => (
          <span key={a.variableId} style={tagStyle}>
            {a.label} = {a.outcomeId}
            <button
              onClick={() => removeAssumption(a.variableId)}
              style={tagCloseStyle}
              aria-label={`Remove assumption ${a.label}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <button onClick={clearAll} style={clearBtnStyle}>
        Clear all
      </button>
    </div>
  );
}

const barStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  padding: "8px 12px",
  borderRadius: "var(--radius-md)",
  background: "rgba(59, 130, 246, 0.08)",
  border: "1px solid rgba(59, 130, 246, 0.25)",
  gap: 8,
};

const tagStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  padding: "2px 8px",
  borderRadius: 4,
  background: "var(--color-primary)",
  color: "#fff",
  fontSize: "0.75rem",
  fontWeight: 600,
};

const tagCloseStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "rgba(255,255,255,0.7)",
  cursor: "pointer",
  fontSize: "0.85rem",
  padding: "0 2px",
  lineHeight: 1,
};

const clearBtnStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--color-primary)",
  cursor: "pointer",
  fontSize: "0.75rem",
  fontWeight: 500,
  whiteSpace: "nowrap",
};
