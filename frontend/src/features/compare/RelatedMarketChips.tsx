import { useMemo } from "react";
import { remapEdgesToMarketIds } from "@/features/graph/deriveEdges";
import type { MarketSummary, NetworkEdgeSummary } from "@/lib/api/types";

export function relatedMarketsFor(
  marketId: string,
  markets: MarketSummary[],
  networkEdges: NetworkEdgeSummary[],
) {
  const byId = new Map(markets.map((market) => [market.id, market]));
  return remapEdgesToMarketIds(
    networkEdges.map((edge) => ({ source: edge.fromVariableId, target: edge.toVariableId })),
    markets,
  ).flatMap((edge) =>
    edge.source === marketId ? [byId.get(edge.target)] : edge.target === marketId ? [byId.get(edge.source)] : [],
  ).filter((market): market is MarketSummary => market !== undefined).slice(0, 8);
}

export function RelatedMarketChips({ marketId, markets, networkEdges, onSelect, label }: {
  marketId: string;
  markets: MarketSummary[];
  networkEdges: NetworkEdgeSummary[];
  onSelect: (marketId: string) => void;
  label: string;
}) {
  const related = useMemo(
    () => relatedMarketsFor(marketId, markets, networkEdges),
    [marketId, markets, networkEdges],
  );

  if (related.length === 0) return null;

  return (
    <div style={rowStyle}>
      <span style={{ color: "var(--color-text-muted)" }}>{label}</span>
      {related.map((market) => (
        <button key={market.id} type="button" onClick={() => onSelect(market.id)} style={chipStyle}>
          {market.title}
        </button>
      ))}
    </div>
  );
}

const rowStyle: React.CSSProperties = { display: "flex", alignItems: "center", flexWrap: "wrap", gap: "var(--space-sm)", fontSize: "0.85rem" };
const chipStyle: React.CSSProperties = { padding: "4px 8px", borderRadius: "var(--radius-md)", border: "1px solid var(--color-border)", background: "var(--color-bg)", color: "var(--color-text-muted)", cursor: "pointer" };
