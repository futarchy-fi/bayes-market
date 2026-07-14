import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorMessage, LoadingPage } from "@/components/ui/Spinner";
import { ReconnectingHint } from "@/components/ui/ReconnectingHint";
import { MarketCombobox } from "@/features/compare/MarketCombobox";
import { RelatedMarketChips, relatedMarketsFor } from "@/features/compare/RelatedMarketChips";
import { jointDistribution } from "@/features/compare/jointMath";
import { useMarket, useMarkets, useNetwork } from "@/lib/query/hooks";

const percent = (value: number) => `${(value * 100).toFixed(2)}%`;

export default function Compare() {
  const [searchParams, setSearchParams] = useSearchParams();
  const marketsQuery = useMarkets();
  const networkQuery = useNetwork();
  const markets = marketsQuery.data?.markets ?? [];
  const requestedA = searchParams.get("a");
  const requestedB = searchParams.get("b");
  const a = markets.some((market) => market.id === requestedA) ? requestedA! : (markets[0]?.id ?? "");
  const networkEdges = networkQuery.data?.edges ?? [];
  const relatedMarkets = useMemo(
    () => relatedMarketsFor(a, markets, networkEdges),
    [a, markets, networkEdges],
  );
  const requestedBIsValid = markets.some((market) => market.id === requestedB);
  const waitingForDefaultB = requestedB === null && networkQuery.isLoading;
  const b = requestedBIsValid
    ? requestedB!
    : waitingForDefaultB
      ? ""
      : requestedB === null
        ? (relatedMarkets[0]?.id ?? markets[1]?.id ?? markets[0]?.id ?? "")
        : (markets[1]?.id ?? markets[0]?.id ?? "");

  const marketA = useMarket(a, { enabled: a.length > 0 });
  const variableA = marketA.data?.market.variableId ?? "";
  const marketBGivenA = useMarket(b, {
    enabled: b.length > 0 && variableA.length > 0,
    context: variableA ? [{ variableId: variableA, outcomeId: "yes" }] : [],
  });
  const marketBGivenNotA = useMarket(b, {
    enabled: b.length > 0 && variableA.length > 0,
    context: variableA ? [{ variableId: variableA, outcomeId: "no" }] : [],
  });

  useEffect(() => {
    if (!a || !b || (requestedA === a && requestedB === b)) return;
    setSearchParams({ a, b }, { replace: true });
  }, [a, b, requestedA, requestedB, setSearchParams]);

  if (marketsQuery.isLoading && markets.length === 0) return <LoadingPage />;
  if (marketsQuery.error && !marketsQuery.data) return <ErrorMessage message="Failed to load markets" />;
  if (markets.length < 2) return <ErrorMessage message="At least two markets are needed to compare." />;

  const error = marketA.error ?? marketBGivenA.error ?? marketBGivenNotA.error;
  const hasComparisonData = Boolean(marketA.data && marketBGivenA.data && marketBGivenNotA.data);
  const isLoading = marketA.isLoading || marketBGivenA.isLoading || marketBGivenNotA.isLoading;
  const pA = marketA.data?.market.marginals.yes;
  const pBGivenA = marketBGivenA.data?.market.marginals.yes;
  const pBGivenNotA = marketBGivenNotA.data?.market.marginals.yes;
  const basePA = pA ?? 0;
  const basePBGivenA = pBGivenA ?? 0;
  const basePBGivenNotA = pBGivenNotA ?? 0;
  const joint = pA == null || pBGivenA == null || pBGivenNotA == null
    ? undefined
    : jointDistribution(basePA, basePBGivenA, basePBGivenNotA);

  function selectMarket(key: "a" | "b", value: string) {
    const next = new URLSearchParams(searchParams);
    next.set(key, value);
    setSearchParams(next);
  }

  return (
    <div style={{ display: "grid", gap: "var(--space-lg)" }}>
      {(marketsQuery.error || (error && hasComparisonData)) && <ReconnectingHint />}
      <header>
        <h1 style={{ fontSize: "1.6rem", fontWeight: 600 }}>Compare Markets</h1>
        <p style={mutedStyle}>Joint probabilities inferred from the current Bayes network.</p>
      </header>

      <section style={{ ...cardStyle, display: "grid", gap: "var(--space-md)" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "var(--space-md)" }}>
          <MarketCombobox label="Market A" value={a} markets={markets} onChange={(value) => selectMarket("a", value)} />
          <MarketCombobox label="Market B" value={b} markets={markets} onChange={(value) => selectMarket("b", value)} />
        </div>
        <RelatedMarketChips
          marketId={a}
          markets={markets}
          networkEdges={networkEdges}
          onSelect={(value) => selectMarket("b", value)}
          label="Related to A:"
        />
      </section>

      {isLoading && !joint && <LoadingPage />}
      {error && !hasComparisonData && <ErrorMessage message={error instanceof Error ? error.message : "Failed to infer comparison"} />}

      {joint && (
        <>
          <section style={cardStyle}>
            <h2 style={sectionTitle}>Joint distribution</h2>
            <div style={{ overflowX: "auto" }}>
              <table style={tableStyle}>
                <thead>
                  <tr><th /><th>B: Yes</th><th>B: No</th><th>A marginal</th></tr>
                </thead>
                <tbody>
                  <tr><th>A: Yes</th><Cell value={joint.p11} /><Cell value={joint.p10} /><Cell value={basePA} marginal /></tr>
                  <tr><th>A: No</th><Cell value={joint.p01} /><Cell value={joint.p00} /><Cell value={1 - basePA} marginal /></tr>
                  <tr><th>B marginal</th><Cell value={joint.pB} marginal /><Cell value={1 - joint.pB} marginal /><Cell value={1} marginal /></tr>
                </tbody>
              </table>
            </div>
          </section>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "var(--space-lg)" }}>
            <section style={cardStyle}>
              <h2 style={sectionTitle}>Conditionals</h2>
              <Stat label="P(B | A=yes)" value={percent(basePBGivenA)} />
              <Stat label="P(B | A=no)" value={percent(basePBGivenNotA)} />
              <Stat label="P(A | B)" value={percent(joint.pAGivenB)} />
              <Stat label="P(A | ~B)" value={percent(joint.pAGivenNotB)} />
            </section>
            <section style={cardStyle}>
              <h2 style={sectionTitle}>Dependence</h2>
              <Stat label="Phi (φ)" value={joint.phi.toFixed(6)} />
              <Stat label="Mutual information" value={`${joint.mutualInformation.toFixed(6)} bits`} />
              {Math.abs(joint.phi) < 1e-6 && (
                <p style={{ ...mutedStyle, marginTop: "var(--space-md)" }}>
                  The joint currently treats these two markets as independent.
                </p>
              )}
            </section>
          </div>
        </>
      )}

      <footer style={{ ...mutedStyle, fontSize: "0.8rem" }}>
        2x2 view inspired by <a href="https://github.com/evand/conditional-markets">Evan Daniel&apos;s conditional-markets viewer</a>.
      </footer>
    </div>
  );
}

function Cell({ value, marginal = false }: { value: number; marginal?: boolean }) {
  return <td style={{ ...cellStyle, color: marginal ? "var(--color-text-muted)" : "var(--color-text)" }}>{percent(value)}</td>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div style={statStyle}><span style={mutedStyle}>{label}</span><strong style={{ fontFamily: "var(--font-mono)" }}>{value}</strong></div>;
}

const cardStyle: React.CSSProperties = { padding: "var(--space-lg)", borderRadius: "var(--radius-lg)", border: "1px solid var(--color-border)", background: "var(--color-bg-surface)" };
const sectionTitle: React.CSSProperties = { fontSize: "1rem", fontWeight: 600, marginBottom: "var(--space-md)" };
const mutedStyle: React.CSSProperties = { color: "var(--color-text-muted)" };
const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "collapse", textAlign: "center" };
const cellStyle: React.CSSProperties = { padding: "var(--space-md)", border: "1px solid var(--color-border)", fontFamily: "var(--font-mono)", fontWeight: 600 };
const statStyle: React.CSSProperties = { display: "flex", justifyContent: "space-between", gap: "var(--space-md)", padding: "var(--space-sm) 0", borderBottom: "1px solid var(--color-border)" };
