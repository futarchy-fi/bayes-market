export function ExchangeUnavailable({ title }: { title: string }) {
  return (
    <section style={style}>
      <strong>{title}</strong>
      <span style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
        Not available in exchange mode.
      </span>
    </section>
  );
}

const style: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: "var(--space-md)",
  padding: "var(--space-md)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius-md)",
  background: "var(--color-bg-surface)",
  fontSize: "0.9rem",
};
