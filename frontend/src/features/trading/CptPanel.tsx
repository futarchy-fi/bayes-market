import { useState } from "react";
import { useCpt, useProbabilityEdit } from "@/lib/query/hooks";
import { useSession } from "@/features/session/context";
import { formatProbability } from "@/lib/utils/format";
import type { Market } from "@/lib/api/types";

interface CptPanelProps {
  market: Market;
}

interface EditingCell {
  entryIndex: number;
  outcomeId: string;
  probability: number;
}

export function CptPanel({ market }: CptPanelProps) {
  const { session, isConfigured } = useSession();
  const { data: cptData, isLoading } = useCpt(market.id);
  const mutation = useProbabilityEdit(market.id);
  const [editing, setEditing] = useState<EditingCell | null>(null);

  if (isLoading) {
    return (
      <div style={panelStyle}>
        <h3 style={headerStyle}>Conditional Probability Table</h3>
        <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>Loading CPT...</div>
      </div>
    );
  }

  if (!cptData) return null;

  const { outcomes, parents, entries } = cptData;
  const hasParents = parents.length > 0;

  const handleCellClick = (entryIndex: number, outcomeId: string, currentP: number) => {
    if (!isConfigured) return;
    setEditing({ entryIndex, outcomeId, probability: currentP });
  };

  const handleSubmit = () => {
    if (!editing || !cptData) return;
    const entry = entries[editing.entryIndex];
    if (!entry) return;

    mutation.mutate(
      {
        payload: {
          accountId: session.accountId,
          variableId: market.variableId,
          target: {
            kind: "marginal",
            outcomeId: editing.outcomeId,
            probability: editing.probability,
          },
          context: entry.context,
          idempotencyKey: crypto.randomUUID(),
        },
        session,
      },
      {
        onSuccess: () => setEditing(null),
      },
    );
  };

  const handleCancel = () => setEditing(null);

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-sm)" }}>
        <h3 style={headerStyle}>Conditional Probability Table</h3>
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted)" }}>
          {entries.length} row{entries.length !== 1 ? "s" : ""}
          {hasParents && ` \u00B7 ${parents.length} parent${parents.length !== 1 ? "s" : ""}`}
        </span>
      </div>

      {!hasParents && (
        <p style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: "var(--space-sm)" }}>
          No parent variables — showing marginal probabilities.
        </p>
      )}

      <div style={{ borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
          <thead>
            <tr style={{ background: "var(--color-bg-hover)" }}>
              {hasParents && <th style={thStyle}>Condition</th>}
              {outcomes.map((o) => (
                <th key={o.id} style={thStyle}>P({o.name})</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, entryIdx) => (
              <tr key={entry.contextKey || "__marginal"} style={{ borderTop: "1px solid var(--color-border)" }}>
                {hasParents && (
                  <td style={{ ...tdStyle, fontFamily: "var(--font-mono)", fontSize: "0.75rem" }}>
                    {entry.context.map((c) => {
                      const parent = parents.find((p) => p.variableId === c.variableId);
                      const outcomeName = parent?.outcomes.find((o) => o.id === c.outcomeId)?.name ?? c.outcomeId;
                      const parentName = parent?.title ?? c.variableId;
                      return `${parentName}=${outcomeName}`;
                    }).join(", ")}
                  </td>
                )}
                {outcomes.map((o) => {
                  const p = entry.marginals[o.id] ?? 0;
                  const isEditing = editing?.entryIndex === entryIdx && editing?.outcomeId === o.id;

                  if (isEditing) {
                    return (
                      <td key={o.id} style={tdStyle}>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                            <input
                              type="range"
                              min={0.01}
                              max={0.99}
                              step={0.01}
                              value={editing.probability}
                              onChange={(e) => setEditing({ ...editing, probability: Number(e.target.value) })}
                              style={{ flex: 1, minWidth: 60 }}
                            />
                            <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", minWidth: 40 }}>
                              {formatProbability(editing.probability)}
                            </span>
                          </div>
                          <div style={{ display: "flex", gap: 4 }}>
                            <button
                              onClick={handleSubmit}
                              disabled={mutation.isPending}
                              style={setBtnStyle}
                            >
                              {mutation.isPending ? "..." : "Set"}
                            </button>
                            <button onClick={handleCancel} style={cancelBtnStyle}>Cancel</button>
                          </div>
                        </div>
                      </td>
                    );
                  }

                  return (
                    <td
                      key={o.id}
                      style={{
                        ...tdStyle,
                        fontFamily: "var(--font-mono)",
                        cursor: isConfigured ? "pointer" : "default",
                        position: "relative",
                      }}
                      onClick={() => handleCellClick(entryIdx, o.id, p)}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <div style={{
                          width: 40,
                          height: 6,
                          borderRadius: 3,
                          background: "var(--color-border)",
                          overflow: "hidden",
                        }}>
                          <div style={{
                            width: `${Math.max(2, p * 100)}%`,
                            height: "100%",
                            borderRadius: 3,
                            background: p > 0.5 ? "var(--color-success)" : "var(--color-info)",
                          }} />
                        </div>
                        <span>{formatProbability(p)}</span>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {mutation.isSuccess && (
        <div style={successStyle}>
          Edit accepted: {mutation.data.order.orderId}
        </div>
      )}

      {mutation.isError && (
        <div style={errorStyle}>
          {mutation.error instanceof Error ? mutation.error.message : "Edit failed"}
        </div>
      )}

      {!isConfigured && (
        <p style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "var(--space-sm)" }}>
          Set your Account ID to edit probabilities.
        </p>
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

const headerStyle: React.CSSProperties = {
  fontSize: "1rem",
  fontWeight: 600,
  margin: 0,
};

const thStyle: React.CSSProperties = {
  textAlign: "left",
  padding: "6px 12px",
  fontWeight: 500,
};

const tdStyle: React.CSSProperties = {
  padding: "6px 12px",
};

const setBtnStyle: React.CSSProperties = {
  padding: "2px 8px",
  borderRadius: "var(--radius-sm)",
  border: "none",
  background: "var(--color-primary)",
  color: "#fff",
  fontWeight: 600,
  fontSize: "0.75rem",
  cursor: "pointer",
};

const cancelBtnStyle: React.CSSProperties = {
  padding: "2px 8px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "transparent",
  color: "var(--color-text-muted)",
  fontSize: "0.75rem",
  cursor: "pointer",
};

const successStyle: React.CSSProperties = {
  marginTop: "var(--space-sm)",
  padding: "var(--space-xs) var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(34, 197, 94, 0.1)",
  border: "1px solid var(--color-success)",
  fontSize: "0.8rem",
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
