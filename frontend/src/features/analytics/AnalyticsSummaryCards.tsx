import type { MarketAnalyticsSummary } from "@/lib/api/types";
import { formatCurrency } from "@/lib/utils/format";

export function AnalyticsSummaryCards({
  summary,
}: {
  summary: MarketAnalyticsSummary;
}) {
  const cards = [
    {
      label: "Total Activity",
      value: summary.totalTrades.toLocaleString(),
      tone: "var(--color-text)",
    },
    {
      label: "Total Volume",
      value: formatCurrency(summary.totalVolume),
      tone: "var(--color-primary-hover)",
    },
    {
      label: "Unique Traders",
      value: summary.uniqueTraders.toLocaleString(),
      tone: "var(--color-success)",
    },
    {
      label: "Last Update",
      value: new Date(summary.lastUpdated).toLocaleString(),
      tone: "var(--color-text)",
    },
  ];

  return (
    <div
      style={{
        display: "grid",
        gap: "var(--space-md)",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
      }}
    >
      {cards.map((card) => (
        <div key={card.label} style={cardStyle}>
          <div style={labelStyle}>{card.label}</div>
          <div style={{ ...valueStyle, color: card.tone }}>{card.value}</div>
          {card.label === "Last Update" && (
            <div style={captionStyle}>
              Accepted activity freshness for the selected market.
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
  minHeight: 112,
};

const labelStyle: React.CSSProperties = {
  fontSize: "0.74rem",
  fontWeight: 700,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--color-text-muted)",
  marginBottom: "var(--space-sm)",
};

const valueStyle: React.CSSProperties = {
  fontSize: "1.25rem",
  fontWeight: 700,
};

const captionStyle: React.CSSProperties = {
  marginTop: "var(--space-sm)",
  fontSize: "0.74rem",
  color: "var(--color-text-muted)",
};
