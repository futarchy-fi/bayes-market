import { useState } from "react";
import { useMarket, useProbabilityEdit } from "@/lib/query/hooks";
import { useSession } from "@/features/session/context";
import { useAssumptions } from "./AssumptionContext";
import { formatProbability } from "@/lib/utils/format";
import type { Market } from "@/lib/api/types";

interface VariableRowProps {
  marketId: string;
  /** Engine variable id for this row's market (from the market summary) */
  variableId?: string;
  /** The market being viewed — edits go through this market's endpoint */
  targetMarket: Market;
}

export function VariableRow({ marketId, variableId, targetMarket }: VariableRowProps) {
  const { session, isConfigured } = useSession();
  const { addAssumption, removeAssumption, hasAssumption, getAssumption, contextPayload } = useAssumptions();
  // Condition this row's marginals on the active assumptions, excluding the
  // row's own variable (the backend rejects self-referential context).
  const rowContext = contextPayload.filter((c) => c.variableId !== variableId);
  const { data } = useMarket(marketId, { context: rowContext });
  const mutation = useProbabilityEdit(targetMarket.id);

  const [editingOutcomeId, setEditingOutcomeId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState(0.5);

  if (!data) return null;

  const m = data.market;
  // Assumptions are keyed by engine variableId, not market id.
  const isAssumed = hasAssumption(m.variableId);
  const assumption = getAssumption(m.variableId);
  const isTargetMarket = m.id === targetMarket.id;

  const handleAssume = (outcomeId: string) => {
    if (isAssumed && assumption?.outcomeId === outcomeId) {
      removeAssumption(m.variableId);
    } else {
      addAssumption({
        variableId: m.variableId,
        outcomeId,
        label: m.title,
      });
    }
  };

  const handleStartEdit = (outcomeId: string, currentP: number) => {
    setEditingOutcomeId(outcomeId);
    setEditValue(currentP);
  };

  const handleSubmitEdit = () => {
    if (!editingOutcomeId || !isConfigured) return;
    mutation.mutate({
      payload: {
        accountId: session.accountId,
        variableId: isTargetMarket ? targetMarket.variableId : m.variableId,
        target: { kind: "marginal", outcomeId: editingOutcomeId, probability: editValue },
        context: contextPayload,
        idempotencyKey: crypto.randomUUID(),
      },
      session,
    });
    setEditingOutcomeId(null);
  };

  return (
    <div style={{
      ...rowStyle,
      ...(isAssumed ? assumedRowStyle : {}),
      ...(isTargetMarket ? targetRowStyle : {}),
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ fontSize: "0.85rem", fontWeight: isTargetMarket ? 700 : 500 }}>
          {m.title}
          {isTargetMarket && <span style={{ fontSize: "0.7rem", color: "var(--color-primary)", marginLeft: 6 }}>(current)</span>}
        </span>
        {isAssumed && (
          <span style={assumedBadge}>
            ASSUMED: {assumption?.outcomeId}
          </span>
        )}
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {m.outcomes.map((o) => {
          const p = m.marginals[o.id] ?? 0;
          const isEditing = editingOutcomeId === o.id;
          const isThisAssumed = isAssumed && assumption?.outcomeId === o.id;

          return (
            <div key={o.id} style={{ flex: 1, minWidth: 100 }}>
              {/* Probability display + inline bar */}
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ height: 20, borderRadius: 4, background: "var(--color-border)", overflow: "hidden", position: "relative" }}>
                    <div style={{
                      height: "100%",
                      width: `${(isEditing ? editValue : p) * 100}%`,
                      borderRadius: 4,
                      background: isThisAssumed ? "var(--color-primary)" : p > 0.5 ? "var(--color-success)" : "var(--color-info)",
                      opacity: isAssumed && !isThisAssumed ? 0.3 : 0.7,
                      transition: "width 0.2s ease",
                    }} />
                    <span style={{
                      position: "absolute",
                      top: 2,
                      left: 6,
                      fontSize: "0.7rem",
                      fontWeight: 600,
                      color: "var(--color-text)",
                    }}>
                      {o.name}: {formatProbability(isEditing ? editValue : p)}
                    </span>
                  </div>
                </div>
              </div>

              {/* Action buttons */}
              <div style={{ display: "flex", gap: 4 }}>
                {!isTargetMarket && (
                  <button
                    onClick={() => handleAssume(o.id)}
                    style={{
                      ...actionBtnStyle,
                      background: isThisAssumed ? "var(--color-primary)" : "transparent",
                      color: isThisAssumed ? "#fff" : "var(--color-primary)",
                      border: `1px solid ${isThisAssumed ? "var(--color-primary)" : "var(--color-border)"}`,
                    }}
                  >
                    {isThisAssumed ? "✓ Assumed" : "Assume"}
                  </button>
                )}
                {isConfigured && !isEditing && (
                  <button
                    onClick={() => handleStartEdit(o.id, p)}
                    style={{ ...actionBtnStyle, border: "1px solid var(--color-border)" }}
                  >
                    Edit
                  </button>
                )}
              </div>

              {/* Inline edit slider */}
              {isEditing && (
                <div style={{ marginTop: 4, display: "flex", gap: 4, alignItems: "center" }}>
                  <input
                    type="range"
                    min={0.01}
                    max={0.99}
                    step={0.01}
                    value={editValue}
                    onChange={(e) => setEditValue(Number(e.target.value))}
                    style={{ flex: 1 }}
                  />
                  <button onClick={handleSubmitEdit} style={submitBtnStyle} disabled={mutation.isPending}>
                    {mutation.isPending ? "…" : "Set"}
                  </button>
                  <button onClick={() => setEditingOutcomeId(null)} style={cancelBtnStyle}>✕</button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {mutation.isSuccess && (
        <div style={{ fontSize: "0.7rem", color: "var(--color-success)", marginTop: 4 }}>
          Edit accepted: {mutation.data.order.orderId}
        </div>
      )}
      {mutation.isError && (
        <div style={{ fontSize: "0.7rem", color: "var(--color-danger)", marginTop: 4 }}>
          {mutation.error instanceof Error ? mutation.error.message : "Edit failed"}
        </div>
      )}
    </div>
  );
}

const rowStyle: React.CSSProperties = {
  padding: "var(--space-sm) var(--space-md)",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
};

const assumedRowStyle: React.CSSProperties = {
  background: "rgba(59, 130, 246, 0.04)",
  borderColor: "rgba(59, 130, 246, 0.2)",
};

const targetRowStyle: React.CSSProperties = {
  borderColor: "var(--color-primary)",
  borderWidth: 2,
};

const assumedBadge: React.CSSProperties = {
  fontSize: "0.65rem",
  fontWeight: 700,
  color: "var(--color-primary)",
  padding: "1px 6px",
  borderRadius: 3,
  background: "rgba(59, 130, 246, 0.1)",
};

const actionBtnStyle: React.CSSProperties = {
  padding: "2px 8px",
  borderRadius: 3,
  background: "transparent",
  color: "var(--color-text)",
  fontSize: "0.7rem",
  fontWeight: 500,
  cursor: "pointer",
};

const submitBtnStyle: React.CSSProperties = {
  padding: "2px 10px",
  borderRadius: 3,
  border: "none",
  background: "var(--color-primary)",
  color: "#fff",
  fontSize: "0.7rem",
  fontWeight: 600,
  cursor: "pointer",
};

const cancelBtnStyle: React.CSSProperties = {
  padding: "2px 6px",
  borderRadius: 3,
  border: "1px solid var(--color-border)",
  background: "transparent",
  color: "var(--color-text-muted)",
  fontSize: "0.7rem",
  cursor: "pointer",
};
