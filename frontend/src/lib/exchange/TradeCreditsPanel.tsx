import { useEffect, useState } from "react";
import { EXCHANGE_API, ExchangeApiError, type NetOrderPreview } from "./client";
import { useNetMarket, usePlaceNetEdit, usePreviewNetEdit } from "./hooks";
import { useExchangeSession } from "./session";
import { isExchangeMode } from "@/lib/exchangeMode";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";

export function friendlyExchangeError(error: unknown): string {
  if (!(error instanceof ExchangeApiError)) return "The exchange request failed. Please try again.";
  if (error.status === 503) return "Credits trading is temporarily unavailable.";
  return ({
    insufficient_credits: "You do not have enough available credits for this stake.",
    market_closed: "This credits market is closed.",
    invalid_target: "Enter a target probability from 0.001 to 0.999.",
    width_budget: "This edit is too complex for the exchange's current width budget.",
  } as Record<string, string>)[error.code] ?? error.message;
}

export function StakePreview({ preview }: { preview: NetOrderPreview }) {
  return (
    <div data-testid="stake-preview" style={{ fontSize: "0.85rem", color: "var(--color-text-muted)" }}>
      Stake to freeze: <strong style={{ color: "var(--color-text)" }}>{preview.stake} credits</strong>
      {" · "}{(preview.before * 100).toFixed(1)}% → {(preview.after * 100).toFixed(1)}%
    </div>
  );
}

export function TradeCreditsPanel({ marketId, variableId }: { marketId: string; variableId: string }) {
  const exchangeMode = isExchangeMode();
  const { isSignedIn } = useExchangeSession();
  const market = useNetMarket(marketId, isSignedIn);
  const preview = usePreviewNetEdit();
  const place = usePlaceNetEdit(marketId);
  const outcomes = market.data?.outcomes ?? [];
  const [outcomeId, setOutcomeId] = useState("");
  const [target, setTarget] = useState("0.5");

  useEffect(() => {
    if (!outcomeId && outcomes[0]) {
      setOutcomeId(outcomes[0].id);
      setTarget(String(market.data?.marginals[outcomes[0].id] ?? 0.5));
    }
  }, [market.data, outcomeId, outcomes]);

  const payload = { variableId, outcomeId, target: Number(target) };
  const resetQuote = () => { preview.reset(); place.reset(); };

  return (
    <section style={panelStyle}>
      <h2 style={{ fontSize: "1.1rem", fontWeight: 600 }}>Trade credits</h2>
      <p style={noteStyle}>{exchangeMode ? "Trades at the live credits exchange venue." : "Trades the credits exchange book, independently of the paper belief flow above."}</p>
      {!isSignedIn ? (
        <a href={`${EXCHANGE_API}/v1/auth/github/login`}>Sign in with GitHub to trade credits</a>
      ) : market.isLoading ? (
        <span style={noteStyle}>Loading live exchange market…</span>
      ) : market.error && !market.data ? (
        <span style={errorStyle}>{friendlyExchangeError(market.error)}</span>
      ) : market.data ? (
        <>
          {market.error && <ReconnectingHint />}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-md)" }}>
            {outcomes.map((outcome) => (
              <span key={outcome.id} style={{ fontSize: "0.85rem" }}>
                {outcome.name}: <strong>{((market.data.marginals[outcome.id] ?? 0) * 100).toFixed(1)}%</strong>
              </span>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(140px, 1fr) minmax(140px, 1fr) auto", gap: "var(--space-sm)", alignItems: "end" }}>
            <label style={labelStyle}>Outcome
              <select value={outcomeId} onChange={(event) => { setOutcomeId(event.target.value); resetQuote(); }} style={inputStyle}>
                {outcomes.map((outcome) => <option key={outcome.id} value={outcome.id}>{outcome.name}</option>)}
              </select>
            </label>
            <label style={labelStyle}>Target probability
              <input aria-label="Target probability" type="number" min="0.001" max="0.999" step="0.001" value={target} onChange={(event) => { setTarget(event.target.value); resetQuote(); }} style={inputStyle} />
            </label>
            <button disabled={!outcomeId || preview.isPending || !Number.isFinite(Number(target))} onClick={() => preview.mutate(payload)} style={buttonStyle}>
              {preview.isPending ? "Previewing…" : "Preview"}
            </button>
          </div>
          {preview.error && <span style={errorStyle}>{friendlyExchangeError(preview.error)}</span>}
          {preview.data && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-md)", alignItems: "center" }}>
              <StakePreview preview={preview.data} />
              <button disabled={place.isPending} onClick={() => place.mutate(payload)} style={buttonStyle}>
                {place.isPending ? "Placing…" : "Place"}
              </button>
            </div>
          )}
          {place.error && <span style={errorStyle}>{friendlyExchangeError(place.error)}</span>}
          {place.data && (
            <div style={{ fontSize: "0.85rem", color: "var(--color-success)" }}>
              Order {place.data.orderId} placed · available balance {place.data.balance.available} credits
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}

const panelStyle: React.CSSProperties = { display: "grid", gap: "var(--space-sm)", padding: "var(--space-md)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", background: "var(--color-bg-surface)" };
const noteStyle: React.CSSProperties = { color: "var(--color-text-muted)", fontSize: "0.8rem" };
const errorStyle: React.CSSProperties = { color: "var(--color-danger)", fontSize: "0.85rem" };
const labelStyle: React.CSSProperties = { display: "grid", gap: "var(--space-xs)", color: "var(--color-text-muted)", fontSize: "0.75rem" };
const inputStyle: React.CSSProperties = { padding: "8px", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border)", background: "var(--color-bg)", color: "var(--color-text)" };
const buttonStyle: React.CSSProperties = { padding: "8px 14px", border: 0, borderRadius: "var(--radius-sm)", background: "var(--color-primary)", color: "white", cursor: "pointer" };
