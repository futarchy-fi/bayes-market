import { Link } from "react-router-dom";
import { AssumptionProvider, useAssumptions } from "@/features/assumptions/AssumptionContext";
import { AssumptionBar } from "@/features/assumptions/AssumptionBar";
import { NetworkMap } from "@/features/graph/NetworkMap";
import { useMarkets } from "@/lib/query/hooks";
import { isExchangeMode } from "@/lib/exchangeMode";

/**
 * Landing: the live belief network is the product, so it is the hero.
 * Click any market to inspect it and assume outcomes; every connected
 * price updates by exact Bayesian inference.
 */
export default function Landing() {
  return (
    <AssumptionProvider>
      <LandingContent />
    </AssumptionProvider>
  );
}

function LandingContent() {
  const exchangeMode = isExchangeMode();
  const { assumptions } = useAssumptions();
  const { data } = useMarkets();
  const marketCount = data?.markets.length ?? 0;

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      <div style={{ maxWidth: 720 }}>
        <h1 style={{ fontSize: "1.9rem", fontWeight: 700, lineHeight: 1.2, marginBottom: "var(--space-sm)" }}>
          A live belief network over AI futures
        </h1>
        <p style={{ color: "var(--color-text-muted)", fontSize: "0.95rem", lineHeight: 1.55 }}>
          {marketCount || 16} linked prediction markets form one coherent probability model.
          Click any market below, assume an outcome, and watch every connected price update
          by exact Bayesian inference — forward to consequences and backward to causes.
        </p>
      </div>

      <AssumptionBar />

      <NetworkMap />

      <div style={{ display: "flex", gap: "var(--space-md)", alignItems: "center", fontSize: "0.85rem" }}>
        <Link to="/markets" style={ctaStyle}>
          Browse markets →
        </Link>
        {!exchangeMode && <Link to="/markets/new" style={secondaryLinkStyle}>
          Create a market
        </Link>}
        <Link to="/system" style={secondaryLinkStyle}>
          System status
        </Link>
        {assumptions.length > 0 && (
          <span style={{ marginLeft: "auto", color: "var(--color-text-muted)", fontSize: "0.75rem" }}>
            Prices shown are conditioned on your {assumptions.length} assumption{assumptions.length > 1 ? "s" : ""}.
          </span>
        )}
      </div>
    </div>
  );
}

const ctaStyle: React.CSSProperties = {
  padding: "6px 14px",
  borderRadius: "var(--radius-sm)",
  background: "var(--color-primary)",
  color: "#fff",
  fontWeight: 600,
  textDecoration: "none",
};

const secondaryLinkStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  textDecoration: "none",
  fontWeight: 500,
};
