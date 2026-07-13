import * as paper from "@/lib/api/client";
import type {
  GraphMarketsResponse,
  Market,
  MarketDetailResponse,
  MarketListFilters,
  MarketListResponse,
  MarketStatus,
  Meta,
  NetworkResponse,
} from "@/lib/api/types";
import * as exchange from "@/lib/exchange/client";
import { isExchangeMode } from "@/lib/exchangeMode";
import { normalizeMarketListFilters } from "@/lib/marketListFilters";

const exchangeMeta = (): Meta => ({
  apiVersion: "exchange",
  timestamp: new Date().toISOString(),
});

function mapNetStatus(status: string): MarketStatus {
  if (status === "open") return "active";
  if (status === "void") return "closed";
  if (status === "active" || status === "resolved" || status === "closed" || status === "draft") return status;
  return "draft";
}

/**
 * Map an exchange net market into the paper Market contract consumed by the UI.
 * `open`/`void` become `active`/`closed`; nullable descriptions become empty
 * strings. The net venue does not expose paper liquidity, volume, or lifecycle
 * timestamps, so those fields use neutral sentinels and the UI labels them as
 * unavailable in exchange mode. IDs, outcomes, and live marginals copy directly.
 */
export function mapNetMarket(market: exchange.NetMarket): Market {
  return {
    id: market.id,
    variableId: market.variableId,
    title: market.title,
    description: market.description ?? "",
    status: mapNetStatus(market.status),
    outcomes: market.outcomes,
    marginals: market.marginals,
    liquidity: 0,
    volume: 0,
    created_at: "",
    expires_at: "",
  };
}

export async function listMarkets(filters: MarketListFilters = {}): Promise<MarketListResponse> {
  if (!isExchangeMode()) return paper.listMarkets(filters);

  const response = await exchange.getNetMarkets();
  const normalized = normalizeMarketListFilters(filters);
  let markets = response.markets.map(mapNetMarket);
  if (normalized.status) markets = markets.filter((market) => market.status === normalized.status);
  if (normalized.q) {
    const query = normalized.q.toLocaleLowerCase();
    markets = markets.filter((market) => market.title.toLocaleLowerCase().includes(query));
  }
  if (normalized.sort) {
    const field = normalized.sort === "created" ? "created_at" : normalized.sort;
    markets.sort((a, b) => String(b[field]).localeCompare(String(a[field]), undefined, { numeric: true }));
  }

  return { markets, count: markets.length, meta: exchangeMeta() };
}

export async function getMarket(
  marketId: string,
  context: paper.MarketContextEntry[] = [],
): Promise<MarketDetailResponse> {
  if (!isExchangeMode()) return paper.getMarket(marketId, context);

  const netMarket = await exchange.getNetMarket(marketId);
  const market = mapNetMarket(netMarket);
  if (context.length > 0) {
    const contextual = await exchange.getNetMarginal(
      netMarket.variableId,
      Object.fromEntries(context.map(({ variableId, outcomeId }) => [variableId, outcomeId])),
    );
    market.marginals = contextual.marginal;
  }
  return { market, meta: exchangeMeta() };
}

export function getNetwork(): Promise<NetworkResponse> {
  return isExchangeMode() ? exchange.getNetNetwork() : paper.getNetwork();
}

export function getGraphMarkets(
  context: paper.MarketContextEntry[] = [],
): Promise<GraphMarketsResponse> {
  return isExchangeMode() ? exchange.getNetGraphMarkets(context) : paper.getGraphMarkets(context);
}
