import * as paper from "@/lib/api/client";
import type {
  GraphMarketsResponse,
  Market,
  MarketDetailResponse,
  MarketListFilters,
  MarketListResponse,
  MarketStatus,
  MarketSummary,
  Meta,
  NetworkResponse,
} from "@/lib/api/types";
import * as exchange from "@/lib/exchange/client";
import { isExchangeMode } from "@/lib/exchangeMode";
import { normalizeMarketListFilters } from "@/lib/marketListFilters";

export interface SystemHealthResponse extends paper.HealthResponse {
  exchange?: exchange.ExchangeHealthResponse;
}

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

function marketProbability(market: MarketSummary): number {
  if (!market.marginals) return -1;
  const p = market.marginals.yes ?? Object.values(market.marginals)[0];
  return typeof p === "number" && Number.isFinite(p) ? p : -1;
}

/**
 * Map an exchange net market into the paper Market contract consumed by the UI.
 * `open`/`void` become `active`/`closed`; nullable descriptions become empty
 * strings. Volume and liquidity copy from the exchange payload when present
 * (defaulting to 0). IDs, outcomes, and live marginals copy directly.
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
    liquidity: market.liquidity ?? 0,
    volume: market.volume ?? 0,
    created_at: "",
    expires_at: "",
  };
}

export function filterMarketList(
  response: MarketListResponse,
  filters: MarketListFilters = {},
  linkCounts?: ReadonlyMap<string, number>,
): MarketListResponse {
  const normalized = normalizeMarketListFilters(filters);
  let markets = [...response.markets];
  if (normalized.status) markets = markets.filter((market) => market.status === normalized.status);
  if (normalized.q) {
    const query = normalized.q.toLocaleLowerCase();
    markets = markets.filter((market) => market.title.toLocaleLowerCase().includes(query));
  }
  if (normalized.sort === "volume") {
    markets.sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0));
  } else if (normalized.sort === "liquidity") {
    markets.sort((a, b) => (b.liquidity ?? 0) - (a.liquidity ?? 0));
  } else if (normalized.sort === "probability") {
    markets.sort((a, b) => marketProbability(b) - marketProbability(a));
  } else if (normalized.sort === "linked") {
    markets.sort((a, b) => (linkCounts?.get(b.id) ?? 0) - (linkCounts?.get(a.id) ?? 0));
  } else if (normalized.sort === "created") {
    markets.sort((a, b) => {
      const aTs = (a as Partial<Market>).created_at ?? "";
      const bTs = (b as Partial<Market>).created_at ?? "";
      return bTs.localeCompare(aTs);
    });
  }
  return { ...response, markets, count: markets.length };
}

export async function listMarkets(filters: MarketListFilters = {}): Promise<MarketListResponse> {
  if (!isExchangeMode()) return paper.listMarkets(filters);

  const response = await exchange.getNetMarkets();
  return filterMarketList({
    markets: response.markets.map(mapNetMarket),
    count: response.count,
    meta: exchangeMeta(),
  }, filters);
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

export async function getHealth(): Promise<SystemHealthResponse> {
  if (!isExchangeMode()) return paper.getHealth();

  const raw = await exchange.getExchangeHealth();
  return {
    service: "futarchy-exchange",
    status: raw.status,
    timestamp: new Date().toISOString(),
    exchange: raw,
  };
}
