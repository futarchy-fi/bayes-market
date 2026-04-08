import { useState } from "react";
import { useSession } from "@/features/session/context";
import { useMarkets, useMarket, useProbabilityEdit } from "@/lib/query/hooks";
import { formatProbability } from "@/lib/utils/format";
import type { Market, MarketSummary } from "@/lib/api/types";

interface ContextAssignment {
  variableId: string;
  outcomeId: string;
}

interface ConditionalEditorProps {
  market: Market;
}

export function ConditionalEditor({ market }: ConditionalEditorProps) {
  const { session, isConfigured } = useSession();
  const mutation = useProbabilityEdit(market.id);
  const { data: marketsData } = useMarkets();

  const [outcomeId, setOutcomeId] = useState(market.outcomes[0]?.id ?? "");
  const [probability, setProbability] = useState(0.5);
  const [context, setContext] = useState<ContextAssignment[]>([]);

  const otherMarkets = (marketsData?.markets ?? []).filter(
    (m) => m.id !== market.id && m.status === "active",
  );

  if (!isConfigured) {
    return (
      <div style={panelStyle}>
        <div style={{ color: "var(--color-text-muted)", textAlign: "center" }}>
          Set your Account ID in the header to use conditional edits.
        </div>
      </div>
    );
  }

  const addContext = () => {
    if (otherMarkets.length === 0) return;
    setContext([...context, { variableId: "", outcomeId: "" }]);
  };

  const removeContext = (idx: number) => {
    setContext(context.filter((_, i) => i !== idx));
  };

  const updateContext = (idx: number, field: keyof ContextAssignment, value: string) => {
    const next = [...context];
    next[idx] = { ...next[idx]!, [field]: value };
    if (field === "variableId") {
      next[idx]!.outcomeId = "";
    }
    setContext(next);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const validContext = context.filter((c) => c.variableId && c.outcomeId);
    mutation.mutate({
      payload: {
        accountId: session.accountId,
        variableId: market.variableId,
        target: { kind: "marginal", outcomeId, probability },
        context: validContext,
        idempotencyKey: crypto.randomUUID(),
      },
      session,
    });
  };

  const hasContext = context.length > 0;

  return (
    <div style={panelStyle}>
      <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "var(--space-sm)" }}>
        Conditional Probability Edit
      </h3>
      <p style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", marginBottom: "var(--space-md)" }}>
        {hasContext
          ? `Set P(${market.outcomes.find((o) => o.id === outcomeId)?.name ?? outcomeId} | ${context
              .filter((c) => c.variableId && c.outcomeId)
              .map((c) => `${c.variableId}=${c.outcomeId}`)
              .join(", ")}) = ${formatProbability(probability)}`
          : `Set P(${market.outcomes.find((o) => o.id === outcomeId)?.name ?? outcomeId}) = ${formatProbability(probability)}`}
      </p>

      <form onSubmit={handleSubmit} style={{ display: "grid", gap: "var(--space-md)" }}>
        {/* Target outcome and probability */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
          <label style={{ fontSize: "0.85rem" }}>
            <span style={labelStyle}>Target Outcome</span>
            <select value={outcomeId} onChange={(e) => setOutcomeId(e.target.value)} style={inputStyle}>
              {market.outcomes.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name} (current: {formatProbability(market.marginals[o.id] ?? 0)})
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.85rem" }}>
            <span style={labelStyle}>New Probability: {formatProbability(probability)}</span>
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

        {/* Context conditions */}
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-sm)" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 500 }}>
              Conditions (given that...)
            </span>
            <button
              type="button"
              onClick={addContext}
              disabled={otherMarkets.length === 0}
              style={addBtnStyle}
            >
              + Add condition
            </button>
          </div>

          {context.length === 0 && (
            <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", padding: "var(--space-sm)", background: "var(--color-bg)", borderRadius: "var(--radius-sm)" }}>
              No conditions — this is an unconditional edit. Add conditions to make it conditional.
            </div>
          )}

          {context.map((c, idx) => (
            <ContextRow
              key={idx}
              assignment={c}
              otherMarkets={otherMarkets}
              onUpdate={(field, value) => updateContext(idx, field, value)}
              onRemove={() => removeContext(idx)}
            />
          ))}
        </div>

        <button
          type="submit"
          disabled={mutation.isPending}
          style={{
            padding: "8px 16px",
            borderRadius: "var(--radius-sm)",
            border: "none",
            background: hasContext ? "var(--color-info)" : "var(--color-primary)",
            color: "#fff",
            fontWeight: 600,
            cursor: mutation.isPending ? "not-allowed" : "pointer",
            opacity: mutation.isPending ? 0.6 : 1,
          }}
        >
          {mutation.isPending
            ? "Submitting…"
            : hasContext
              ? "Submit Conditional Edit"
              : "Submit Unconditional Edit"}
        </button>
      </form>

      {mutation.isSuccess && (
        <div style={successStyle}>
          {hasContext ? "Conditional edit" : "Edit"} accepted: {mutation.data.order.orderId}
        </div>
      )}

      {mutation.isError && (
        <div style={errorStyle}>
          {mutation.error instanceof Error ? mutation.error.message : "Edit failed"}
        </div>
      )}
    </div>
  );
}

function ContextRow({
  assignment,
  otherMarkets,
  onUpdate,
  onRemove,
}: {
  assignment: ContextAssignment;
  otherMarkets: MarketSummary[];
  onUpdate: (field: keyof ContextAssignment, value: string) => void;
  onRemove: () => void;
}) {
  const { data } = useMarket(assignment.variableId, { enabled: !!assignment.variableId });
  const outcomes = data?.market.outcomes ?? [];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: "var(--space-sm)", marginBottom: "var(--space-sm)" }}>
      <select
        value={assignment.variableId}
        onChange={(e) => onUpdate("variableId", e.target.value)}
        style={inputStyle}
      >
        <option value="">Select market...</option>
        {otherMarkets.map((m) => (
          <option key={m.id} value={m.id}>{m.title}</option>
        ))}
      </select>
      <select
        value={assignment.outcomeId}
        onChange={(e) => onUpdate("outcomeId", e.target.value)}
        style={inputStyle}
        disabled={!assignment.variableId}
      >
        <option value="">Select outcome...</option>
        {outcomes.map((o) => (
          <option key={o.id} value={o.id}>{o.name}</option>
        ))}
      </select>
      <button type="button" onClick={onRemove} style={removeBtnStyle}>×</button>
    </div>
  );
}

const panelStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  color: "var(--color-text-muted)",
  marginBottom: "var(--space-xs)",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.875rem",
};

const addBtnStyle: React.CSSProperties = {
  padding: "4px 10px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "transparent",
  color: "var(--color-primary)",
  fontSize: "0.8rem",
  cursor: "pointer",
};

const removeBtnStyle: React.CSSProperties = {
  padding: "4px 8px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "transparent",
  color: "var(--color-danger)",
  fontSize: "1rem",
  cursor: "pointer",
  lineHeight: 1,
};

const successStyle: React.CSSProperties = {
  marginTop: "var(--space-md)",
  padding: "var(--space-sm) var(--space-md)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(34, 197, 94, 0.1)",
  border: "1px solid var(--color-success)",
  fontSize: "0.85rem",
};

const errorStyle: React.CSSProperties = {
  marginTop: "var(--space-md)",
  padding: "var(--space-sm) var(--space-md)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(239, 68, 68, 0.1)",
  border: "1px solid var(--color-danger)",
  fontSize: "0.85rem",
  color: "var(--color-danger)",
};
