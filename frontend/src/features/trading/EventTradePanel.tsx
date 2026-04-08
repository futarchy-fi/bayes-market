import { useState } from "react";
import { useEventTrade } from "@/lib/query/hooks";
import { useSession } from "@/features/session/context";
import type { Market } from "@/lib/api/types";

interface Props {
  market: Market;
}

export function EventTradePanel({ market }: Props) {
  const { session, isConfigured } = useSession();
  const mutation = useEventTrade(market.id);
  const [selectedOutcome, setSelectedOutcome] = useState<string>("");
  const [side, setSide] = useState<"buy" | "sell">("buy");

  if (market.status !== "active") return null;
  if (!isConfigured) return null;

  const currentPrice = selectedOutcome ? (market.marginals[selectedOutcome] ?? 0) : 0;

  const handleTrade = () => {
    if (!selectedOutcome) return;

    mutation.mutate({
      payload: {
        accountId: session.accountId,
        formula: [[{
          variableId: market.id,
          outcomeId: selectedOutcome,
          negated: false,
        }]],
        side,
        idempotencyKey: crypto.randomUUID(),
      },
      session,
    });
  };

  return (
    <div style={panelStyle}>
      <div style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>
        Quick Trade
      </div>

      <div style={{ display: "flex", gap: "var(--space-sm)", alignItems: "center", flexWrap: "wrap" }}>
        {/* Side toggle */}
        <div style={{ display: "flex", borderRadius: "var(--radius-sm)", overflow: "hidden", border: "1px solid var(--color-border)" }}>
          <button
            onClick={() => setSide("buy")}
            style={{
              ...sideBtnStyle,
              background: side === "buy" ? "var(--color-success, #22c55e)" : "transparent",
              color: side === "buy" ? "#fff" : "var(--color-text-muted)",
            }}
          >
            Buy
          </button>
          <button
            onClick={() => setSide("sell")}
            style={{
              ...sideBtnStyle,
              background: side === "sell" ? "var(--color-danger, #ef4444)" : "transparent",
              color: side === "sell" ? "#fff" : "var(--color-text-muted)",
            }}
          >
            Sell
          </button>
        </div>

        {/* Outcome selector */}
        <select
          value={selectedOutcome}
          onChange={(e) => setSelectedOutcome(e.target.value)}
          style={selectStyle}
        >
          <option value="">Select outcome...</option>
          {market.outcomes.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name} @ {((market.marginals[o.id] ?? 0) * 100).toFixed(1)}%
            </option>
          ))}
        </select>

        {selectedOutcome && (
          <span style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
            Price: {(currentPrice * 100).toFixed(1)}%
          </span>
        )}

        <button
          onClick={handleTrade}
          disabled={!selectedOutcome || mutation.isPending}
          style={{
            ...tradeBtnStyle,
            background: side === "buy" ? "var(--color-success, #22c55e)" : "var(--color-danger, #ef4444)",
            opacity: selectedOutcome ? 1 : 0.5,
            cursor: selectedOutcome && !mutation.isPending ? "pointer" : "not-allowed",
          }}
        >
          {mutation.isPending
            ? "Submitting..."
            : `${side === "buy" ? "Buy" : "Sell"} ${selectedOutcome || "..."}`}
        </button>
      </div>

      {mutation.isSuccess && (
        <div style={successStyle}>
          Trade accepted — Order {mutation.data.order.orderId}
        </div>
      )}

      {mutation.isError && (
        <div style={errorStyle}>
          {mutation.error instanceof Error ? mutation.error.message : "Trade failed"}
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

const sideBtnStyle: React.CSSProperties = {
  padding: "4px 14px",
  border: "none",
  fontSize: "0.8rem",
  fontWeight: 600,
  cursor: "pointer",
};

const selectStyle: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.85rem",
};

const tradeBtnStyle: React.CSSProperties = {
  padding: "6px 16px",
  borderRadius: "var(--radius-sm)",
  border: "none",
  color: "#fff",
  fontWeight: 600,
  fontSize: "0.85rem",
};

const successStyle: React.CSSProperties = {
  marginTop: "var(--space-sm)",
  padding: "var(--space-xs) var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(34, 197, 94, 0.1)",
  border: "1px solid var(--color-success, #22c55e)",
  fontSize: "0.8rem",
  color: "var(--color-success, #22c55e)",
};

const errorStyle: React.CSSProperties = {
  marginTop: "var(--space-sm)",
  padding: "var(--space-xs) var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(239, 68, 68, 0.1)",
  border: "1px solid var(--color-danger)",
  fontSize: "0.8rem",
  color: "var(--color-danger)",
};
