import { useState } from "react";
import { useEventTrade } from "@/lib/query/hooks";
import { useSession } from "@/features/session/context";
import type { EventTradeOrder, Market } from "@/lib/api/types";

function TradeReceipt({ order, outcomeLabel }: { order: EventTradeOrder; outcomeLabel: string }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "var(--space-sm)", marginTop: "var(--space-xs)", fontSize: "0.75rem" }}>
      <div>
        <div style={{ color: "var(--color-text-muted)" }}>Side</div>
        <div style={{ fontFamily: "var(--font-mono)" }}>{order.side}</div>
      </div>
      <div>
        <div style={{ color: "var(--color-text-muted)" }}>Outcome</div>
        <div style={{ fontFamily: "var(--font-mono)" }}>{outcomeLabel}</div>
      </div>
      <div>
        <div style={{ color: "var(--color-text-muted)" }}>Size</div>
        <div style={{ fontFamily: "var(--font-mono)" }}>{order.size.toFixed(2)}</div>
      </div>
      <div>
        <div style={{ color: "var(--color-text-muted)" }}>Price</div>
        <div style={{ fontFamily: "var(--font-mono)" }}>{(order.price * 100).toFixed(1)}%</div>
      </div>
      <div>
        <div style={{ color: "var(--color-text-muted)" }}>Notional</div>
        <div style={{ fontFamily: "var(--font-mono)" }}>{order.notional.toFixed(2)}</div>
      </div>
    </div>
  );
}

interface Props {
  market: Market;
}

export function EventTradePanel({ market }: Props) {
  const { session, isConfigured } = useSession();
  const mutation = useEventTrade(market.id);
  const [selectedOutcome, setSelectedOutcome] = useState<string>("");
  const [size, setSize] = useState<string>("1");
  const [side, setSide] = useState<"buy" | "sell">("buy");

  if (market.status !== "active") return null;
  if (!isConfigured) return null;

  const currentPrice = selectedOutcome ? (market.marginals[selectedOutcome] ?? 0) : 0;
  const parsedSize = Number(size);
  const isValidSize = Number.isFinite(parsedSize) && parsedSize > 0;
  const canSubmit = selectedOutcome.length > 0 && isValidSize && !mutation.isPending;

  const handleTrade = () => {
    if (!selectedOutcome || !isValidSize) return;

    mutation.mutate({
      payload: {
        accountId: session.accountId,
        formula: [[{
          variableId: market.id,
          outcomeId: selectedOutcome,
          negated: false,
        }]],
        size: parsedSize,
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

        <input
          type="number"
          inputMode="decimal"
          min="0.000001"
          step="0.1"
          value={size}
          onChange={(e) => setSize(e.target.value)}
          style={sizeInputStyle}
          aria-label="Trade size"
        />

        <button
          onClick={handleTrade}
          disabled={!canSubmit}
          style={{
            ...tradeBtnStyle,
            background: side === "buy" ? "var(--color-success, #22c55e)" : "var(--color-danger, #ef4444)",
            opacity: canSubmit ? 1 : 0.5,
            cursor: canSubmit ? "pointer" : "not-allowed",
          }}
        >
          {mutation.isPending
            ? "Submitting..."
            : `${side === "buy" ? "Buy" : "Sell"} ${selectedOutcome || "..."} (${size || "0"})`}
        </button>
      </div>

      {mutation.isSuccess && (
        <div style={successStyle}>
          <div>Trade accepted - Order {mutation.data.order.id}</div>
          <TradeReceipt
            order={mutation.data.order}
            outcomeLabel={
              market.outcomes.find((outcome) => outcome.id === mutation.data.order.targetOutcomeId)?.name
              ?? mutation.data.order.targetOutcomeId
            }
          />
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

const sizeInputStyle: React.CSSProperties = {
  ...selectStyle,
  width: "96px",
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
