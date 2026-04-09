import type {
  MarketListFilters,
  MarketListSort,
  MarketListStatusFilter,
  MarketStatus,
} from "@/lib/api/types";

export interface NormalizedMarketListFilters {
  status?: MarketStatus;
  sort?: MarketListSort;
  q?: string;
}

export interface MarketListQueryKeyFilters {
  status: MarketStatus | null;
  sort: MarketListSort | null;
  q: string | null;
}

const MARKET_STATUSES: MarketStatus[] = ["active", "resolved", "closed", "draft"];
const MARKET_SORTS: MarketListSort[] = ["volume", "liquidity", "created"];

export function isMarketListStatusFilter(value: string | null): value is MarketListStatusFilter {
  return value === "all" || MARKET_STATUSES.includes(value as MarketStatus);
}

export function isMarketListSort(value: string | null): value is MarketListSort {
  return MARKET_SORTS.includes(value as MarketListSort);
}

export function normalizeMarketListFilters(
  filters: MarketListFilters = {},
): NormalizedMarketListFilters {
  const normalized: NormalizedMarketListFilters = {};

  if (filters.status && filters.status !== "all") {
    normalized.status = filters.status;
  }

  if (filters.sort) {
    normalized.sort = filters.sort;
  }

  const q = filters.q?.trim();
  if (q) {
    normalized.q = q;
  }

  return normalized;
}

export function marketListQueryKey(
  filters: MarketListFilters = {},
): MarketListQueryKeyFilters {
  const normalized = normalizeMarketListFilters(filters);

  return {
    status: normalized.status ?? null,
    sort: normalized.sort ?? null,
    q: normalized.q ?? null,
  };
}

export function marketListSearchParams(
  filters: MarketListFilters = {},
): URLSearchParams {
  const normalized = normalizeMarketListFilters(filters);
  const params = new URLSearchParams();

  if (normalized.status) {
    params.set("status", normalized.status);
  }

  if (normalized.sort) {
    params.set("sort", normalized.sort);
  }

  if (normalized.q) {
    params.set("q", normalized.q);
  }

  return params;
}

export function readMarketListFiltersFromSearchParams(
  searchParams: URLSearchParams,
): NormalizedMarketListFilters {
  const status = searchParams.get("status");
  const sort = searchParams.get("sort");

  return normalizeMarketListFilters({
    status: isMarketListStatusFilter(status) ? status : undefined,
    sort: isMarketListSort(sort) ? sort : undefined,
    q: searchParams.get("q") ?? undefined,
  });
}
