import { formatProbability } from "@/lib/utils/format";
import type { MarketOutcome } from "@/lib/api/types";

const OUTCOME_COLORS = [
  "#22c55e", "#ef4444", "#3b82f6", "#eab308", "#a855f7",
  "#ec4899", "#14b8a6", "#f97316",
];

interface ProbabilityBarProps {
  outcomes: MarketOutcome[];
  marginals: Record<string, number>;
  /** When true, briefly highlights the bar to signal a propagation wave arrival */
  highlight?: boolean;
}

export function ProbabilityBar({ outcomes, marginals, highlight }: ProbabilityBarProps) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          height: 24,
          borderRadius: "var(--radius-sm)",
          overflow: "hidden",
          background: "var(--color-bg)",
          boxShadow: highlight ? "0 0 8px var(--color-info)" : "none",
          transition: "box-shadow 0.3s ease",
        }}
      >
        {outcomes.map((o, i) => {
          const p = marginals[o.id] ?? 0;
          return (
            <div
              key={o.id}
              style={{
                width: `${p * 100}%`,
                background: OUTCOME_COLORS[i % OUTCOME_COLORS.length],
                transition: "width 0.3s ease",
                minWidth: p > 0 ? 2 : 0,
              }}
              title={`${o.name}: ${formatProbability(p)}`}
            />
          );
        })}
      </div>
      <div style={{ display: "flex", gap: "var(--space-md)", marginTop: "var(--space-xs)", fontSize: "0.8rem" }}>
        {outcomes.map((o, i) => (
          <span key={o.id} style={{ color: OUTCOME_COLORS[i % OUTCOME_COLORS.length] }}>
            {o.name} {formatProbability(marginals[o.id] ?? 0)}
          </span>
        ))}
      </div>
    </div>
  );
}
