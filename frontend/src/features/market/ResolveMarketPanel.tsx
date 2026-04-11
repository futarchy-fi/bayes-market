import { useState } from "react";
import { useResolveMarket } from "@/lib/query/hooks";
import { useSession } from "@/features/session/context";
import type { Market } from "@/lib/api/types";

interface Props {
  market: Market;
}

export function ResolveMarketPanel({ market }: Props) {
  const { session } = useSession();
  const mutation = useResolveMarket(market.id);
  const [selectedOutcome, setSelectedOutcome] = useState<string>("");
  const [confirming, setConfirming] = useState(false);
  const resolvedSummary = market.resolution
    ? `Outcome: ${market.resolution}`
    : market.resolutionProbabilities
      ? `Distribution: ${formatResolutionProbabilities(market.resolutionProbabilities)}`
      : "Resolution finalized";

  if (market.status === "resolved") {
    return (
      <div style={resolvedStyle}>
        <span style={{ fontWeight: 600, fontSize: "0.85rem" }}>Resolved</span>
        <span style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
          <strong>{resolvedSummary}</strong>
        </span>
      </div>
    );
  }

  if (market.status !== "active" && market.status !== "closed") {
    return null;
  }

  if (!session.accountId) {
    return null;
  }

  const handleResolve = () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }

    mutation.mutate(
      {
        payload: {
          accountId: session.accountId,
          outcomeId: selectedOutcome,
        },
        session,
      },
      {
        onSuccess: () => {
          setConfirming(false);
          setSelectedOutcome("");
        },
        onError: () => {
          setConfirming(false);
        },
      },
    );
  };

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)", marginBottom: "var(--space-sm)" }}>
        <span style={{ fontWeight: 600, fontSize: "0.85rem" }}>Resolve Market</span>
      </div>

      <div style={{ display: "flex", gap: "var(--space-sm)", alignItems: "center", flexWrap: "wrap" }}>
        <select
          value={selectedOutcome}
          onChange={(e) => {
            setSelectedOutcome(e.target.value);
            setConfirming(false);
          }}
          style={selectStyle}
        >
          <option value="">Select winning outcome...</option>
          {market.outcomes.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name} ({o.id})
            </option>
          ))}
        </select>

        {confirming ? (
          <div style={{ display: "flex", gap: "var(--space-xs)", alignItems: "center" }}>
            <span style={{ fontSize: "0.8rem", color: "var(--color-danger)", fontWeight: 500 }}>
              Confirm resolve to &ldquo;{selectedOutcome}&rdquo;?
            </span>
            <button
              onClick={handleResolve}
              disabled={mutation.isPending}
              style={confirmBtnStyle}
            >
              {mutation.isPending ? "Resolving..." : "Yes, Resolve"}
            </button>
            <button
              onClick={() => setConfirming(false)}
              style={cancelBtnStyle}
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={handleResolve}
            disabled={!selectedOutcome || mutation.isPending}
            style={{
              ...resolveBtnStyle,
              opacity: selectedOutcome ? 1 : 0.5,
              cursor: selectedOutcome ? "pointer" : "not-allowed",
            }}
          >
            Resolve
          </button>
        )}
      </div>

      {mutation.isError && (
        <div style={errorStyle}>
          {mutation.error instanceof Error ? mutation.error.message : "Resolution failed"}
        </div>
      )}

      {mutation.isSuccess && (
        <div style={successStyle}>
          Market resolved successfully.
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

const resolvedStyle: React.CSSProperties = {
  ...panelStyle,
  display: "flex",
  gap: "var(--space-md)",
  alignItems: "center",
  borderColor: "var(--color-success, #22c55e)",
  background: "rgba(34, 197, 94, 0.05)",
};

const selectStyle: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.85rem",
};

const resolveBtnStyle: React.CSSProperties = {
  padding: "6px 16px",
  borderRadius: "var(--radius-sm)",
  border: "none",
  background: "var(--color-danger, #ef4444)",
  color: "#fff",
  fontWeight: 600,
  fontSize: "0.85rem",
};

const confirmBtnStyle: React.CSSProperties = {
  padding: "6px 14px",
  borderRadius: "var(--radius-sm)",
  border: "none",
  background: "var(--color-danger, #ef4444)",
  color: "#fff",
  fontWeight: 600,
  fontSize: "0.8rem",
  cursor: "pointer",
};

const cancelBtnStyle: React.CSSProperties = {
  padding: "6px 14px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "transparent",
  color: "var(--color-text-muted)",
  fontSize: "0.8rem",
  cursor: "pointer",
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

const successStyle: React.CSSProperties = {
  marginTop: "var(--space-sm)",
  padding: "var(--space-xs) var(--space-sm)",
  borderRadius: "var(--radius-sm)",
  background: "rgba(34, 197, 94, 0.1)",
  border: "1px solid var(--color-success, #22c55e)",
  fontSize: "0.8rem",
  color: "var(--color-success, #22c55e)",
};

function formatResolutionProbabilities(resolutionProbabilities: Record<string, number>): string {
  return Object.entries(resolutionProbabilities)
    .map(([outcomeId, probability]) => `${outcomeId} ${(probability * 100).toFixed(1)}%`)
    .join(", ");
}
