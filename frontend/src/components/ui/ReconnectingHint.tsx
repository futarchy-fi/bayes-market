export function ReconnectingHint() {
  return (
    <span
      role="status"
      style={{
        width: "fit-content",
        padding: "3px 8px",
        borderRadius: 999,
        background: "var(--color-bg-hover)",
        color: "var(--color-text-muted)",
        fontSize: "0.75rem",
      }}
    >
      reconnecting…
    </span>
  );
}
