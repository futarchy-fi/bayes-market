import { statusColor } from "@/lib/utils/format";

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: "var(--radius-sm)",
        fontSize: "0.75rem",
        fontWeight: 600,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        color: statusColor(status),
        border: `1px solid ${statusColor(status)}`,
        background: "transparent",
      }}
    >
      {status}
    </span>
  );
}
