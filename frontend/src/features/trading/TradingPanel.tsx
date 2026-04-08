import { useState } from "react";
import { useSession } from "@/features/session/context";
import { useProbabilityEdit } from "@/lib/query/hooks";
import { formatProbability } from "@/lib/utils/format";
import type { Market } from "@/lib/api/types";

interface TradingPanelProps {
  market: Market;
}

export function TradingPanel({ market }: TradingPanelProps) {
  const { session, isConfigured } = useSession();
  const mutation = useProbabilityEdit(market.id);

  const [outcomeId, setOutcomeId] = useState(market.outcomes[0]?.id ?? "");
  const [probability, setProbability] = useState(0.5);

  if (!isConfigured) {
    return (
      <div style={{
        padding: "var(--space-md)",
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--color-border)",
        background: "var(--color-bg-surface)",
        color: "var(--color-text-muted)",
        textAlign: "center",
      }}>
        Set your Account ID in the header to trade.
      </div>
    );
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate({
      payload: {
        accountId: session.accountId,
        variableId: market.variableId,
        target: { kind: "marginal", outcomeId, probability },
        context: [],
        idempotencyKey: crypto.randomUUID(),
      },
      session,
    });
  };

  return (
    <div style={{
      padding: "var(--space-md)",
      borderRadius: "var(--radius-md)",
      border: "1px solid var(--color-border)",
      background: "var(--color-bg-surface)",
    }}>
      <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "var(--space-md)" }}>Probability Edit</h3>
      <form onSubmit={handleSubmit} style={{ display: "grid", gap: "var(--space-md)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
          <label style={{ fontSize: "0.85rem" }}>
            <span style={{ display: "block", color: "var(--color-text-muted)", marginBottom: "var(--space-xs)" }}>Outcome</span>
            <select
              value={outcomeId}
              onChange={(e) => setOutcomeId(e.target.value)}
              style={inputStyle}
            >
              {market.outcomes.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name} ({formatProbability(market.marginals[o.id] ?? 0)})
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.85rem" }}>
            <span style={{ display: "block", color: "var(--color-text-muted)", marginBottom: "var(--space-xs)" }}>
              New Probability: {formatProbability(probability)}
            </span>
            <input
              type="range"
              min={0.01}
              max={0.99}
              step={0.01}
              value={probability}
              onChange={(e) => setProbability(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </label>
        </div>
        <button
          type="submit"
          disabled={mutation.isPending}
          style={{
            padding: "8px 16px",
            borderRadius: "var(--radius-sm)",
            border: "none",
            background: "var(--color-primary)",
            color: "#fff",
            fontWeight: 600,
            cursor: mutation.isPending ? "not-allowed" : "pointer",
            opacity: mutation.isPending ? 0.6 : 1,
          }}
        >
          {mutation.isPending ? "Submitting…" : "Submit Edit"}
        </button>
      </form>

      {mutation.isSuccess && (
        <div style={{
          marginTop: "var(--space-md)",
          padding: "var(--space-sm) var(--space-md)",
          borderRadius: "var(--radius-sm)",
          background: "rgba(34, 197, 94, 0.1)",
          border: "1px solid var(--color-success)",
          fontSize: "0.85rem",
        }}>
          Order accepted: {mutation.data.order.orderId}
        </div>
      )}

      {mutation.isError && (
        <div style={{
          marginTop: "var(--space-md)",
          padding: "var(--space-sm) var(--space-md)",
          borderRadius: "var(--radius-sm)",
          background: "rgba(239, 68, 68, 0.1)",
          border: "1px solid var(--color-danger)",
          fontSize: "0.85rem",
          color: "var(--color-danger)",
        }}>
          {mutation.error instanceof Error ? mutation.error.message : "Trade failed"}
        </div>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.875rem",
};
