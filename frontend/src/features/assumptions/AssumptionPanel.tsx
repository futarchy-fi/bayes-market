import { useMarkets } from "@/lib/query/hooks";
import { useAssumptions } from "./AssumptionContext";
import { AssumptionBar } from "./AssumptionBar";
import { VariableRow } from "./VariableRow";
import type { Market } from "@/lib/api/types";

interface AssumptionPanelProps {
  market: Market;
}

export function AssumptionPanel({ market }: AssumptionPanelProps) {
  const { data: marketsData } = useMarkets();
  const { assumptions } = useAssumptions();

  const allMarkets = marketsData?.markets ?? [];
  const activeMarkets = allMarkets.filter((m) => m.status === "active");

  // Show current market first, then others
  const sortedRows = [
    { id: market.id, variableId: market.variableId },
    ...activeMarkets
      .filter((m) => m.id !== market.id)
      .map((m) => ({ id: m.id, variableId: m.variableId })),
  ];

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "var(--space-sm)" }}>
        <h3 style={{ fontSize: "1rem", fontWeight: 600 }}>
          Variables & Assumptions
        </h3>
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          {assumptions.length > 0
            ? `Showing conditionals given ${assumptions.length} assumption${assumptions.length > 1 ? "s" : ""}`
            : "Showing marginal probabilities"}
        </span>
      </div>

      <AssumptionBar />

      <div style={{ display: "grid", gap: "var(--space-sm)", marginTop: "var(--space-sm)" }}>
        {sortedRows.map((row) => (
          <VariableRow key={row.id} marketId={row.id} variableId={row.variableId} targetMarket={market} />
        ))}
      </div>

      {activeMarkets.length <= 1 && (
        <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", textAlign: "center", padding: "var(--space-md)" }}>
          Create more markets to use assumptions — assumptions let you condition on other variables.
        </div>
      )}
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};
