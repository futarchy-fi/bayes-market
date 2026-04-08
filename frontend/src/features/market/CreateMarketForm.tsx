import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCreateMarket } from "@/lib/query/hooks";
import { useSession } from "@/features/session/context";

interface OutcomeInput {
  id: string;
  name: string;
}

export function CreateMarketForm() {
  const navigate = useNavigate();
  const { session } = useSession();
  const mutation = useCreateMarket();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [liquidity, setLiquidity] = useState("10000");
  const [outcomes, setOutcomes] = useState<OutcomeInput[]>([
    { id: "yes", name: "Yes" },
    { id: "no", name: "No" },
  ]);

  const addOutcome = () => {
    const n = outcomes.length + 1;
    setOutcomes([...outcomes, { id: `o${n}`, name: `Option ${n}` }]);
  };

  const removeOutcome = (idx: number) => {
    if (outcomes.length <= 2) return;
    setOutcomes(outcomes.filter((_, i) => i !== idx));
  };

  const updateOutcome = (idx: number, field: keyof OutcomeInput, value: string) => {
    const next = [...outcomes];
    next[idx] = { ...next[idx]!, [field]: value };
    setOutcomes(next);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    mutation.mutate(
      {
        payload: {
          title,
          description,
          outcomes,
          expires_at: new Date(expiresAt).toISOString(),
          liquidity: Number(liquidity) || 10000,
        },
        session: session.accountId ? session : undefined,
      },
      {
        onSuccess: (data) => {
          navigate(`/markets/${data.market.id}`);
        },
      },
    );
  };

  const isValid = title.trim().length > 0 && expiresAt.length > 0 && outcomes.every((o) => o.id && o.name);

  return (
    <div style={{ maxWidth: 600, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.5rem", fontWeight: 600, marginBottom: "var(--space-lg)" }}>
        Create Market
      </h1>

      <form onSubmit={handleSubmit} style={{ display: "grid", gap: "var(--space-md)" }}>
        <label style={labelWrapStyle}>
          <span style={labelStyle}>Question / Title</span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Will ETH trade above $5000 by December?"
            style={inputStyle}
            required
          />
        </label>

        <label style={labelWrapStyle}>
          <span style={labelStyle}>Description (optional)</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Additional context about resolution criteria..."
            rows={3}
            style={{ ...inputStyle, resize: "vertical" }}
          />
        </label>

        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-sm)" }}>
            <span style={labelStyle}>Outcomes (min 2)</span>
            <button type="button" onClick={addOutcome} style={addBtnStyle}>+ Add outcome</button>
          </div>
          <div style={{ display: "grid", gap: "var(--space-sm)" }}>
            {outcomes.map((o, idx) => (
              <div key={idx} style={{ display: "grid", gridTemplateColumns: "1fr 2fr auto", gap: "var(--space-sm)" }}>
                <input
                  type="text"
                  value={o.id}
                  onChange={(e) => updateOutcome(idx, "id", e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))}
                  placeholder="id"
                  style={{ ...inputStyle, fontFamily: "var(--font-mono)", fontSize: "0.8rem" }}
                />
                <input
                  type="text"
                  value={o.name}
                  onChange={(e) => updateOutcome(idx, "name", e.target.value)}
                  placeholder="Display name"
                  style={inputStyle}
                />
                <button
                  type="button"
                  onClick={() => removeOutcome(idx)}
                  disabled={outcomes.length <= 2}
                  style={removeBtnStyle}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
          <label style={labelWrapStyle}>
            <span style={labelStyle}>Expiry Date</span>
            <input
              type="datetime-local"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
              style={inputStyle}
              required
            />
          </label>
          <label style={labelWrapStyle}>
            <span style={labelStyle}>Initial Liquidity</span>
            <input
              type="number"
              value={liquidity}
              onChange={(e) => setLiquidity(e.target.value)}
              min={100}
              step={1000}
              style={inputStyle}
            />
          </label>
        </div>

        {/* Preview */}
        <div style={previewStyle}>
          <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--color-text-muted)" }}>PREVIEW</span>
          <div style={{ fontSize: "0.9rem", fontWeight: 600, marginTop: 4 }}>{title || "Untitled market"}</div>
          <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", marginTop: 2 }}>
            {outcomes.length} outcomes · {`1/${outcomes.length}`} uniform prior · ${Number(liquidity).toLocaleString()} liquidity
          </div>
        </div>

        <button
          type="submit"
          disabled={!isValid || mutation.isPending}
          style={{
            padding: "10px 20px",
            borderRadius: "var(--radius-sm)",
            border: "none",
            background: isValid ? "var(--color-primary)" : "var(--color-border)",
            color: "#fff",
            fontWeight: 600,
            fontSize: "0.9rem",
            cursor: isValid && !mutation.isPending ? "pointer" : "not-allowed",
            opacity: mutation.isPending ? 0.6 : 1,
          }}
        >
          {mutation.isPending ? "Creating…" : "Create Market"}
        </button>
      </form>

      {mutation.isError && (
        <div style={errorStyle}>
          {mutation.error instanceof Error ? mutation.error.message : "Failed to create market"}
        </div>
      )}
    </div>
  );
}

const labelWrapStyle: React.CSSProperties = { display: "block" };
const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: "0.85rem",
  fontWeight: 500,
  color: "var(--color-text-muted)",
  marginBottom: "var(--space-xs)",
};
const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 12px",
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
const previewStyle: React.CSSProperties = {
  padding: "var(--space-md)",
  borderRadius: "var(--radius-md)",
  border: "1px dashed var(--color-border)",
  background: "var(--color-bg)",
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
