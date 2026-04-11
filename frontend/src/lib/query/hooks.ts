import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api/client";
import type {
  AnalyticsInterval,
  ProbabilityEditPayload,
  EventTradePayload,
  CommentPayload,
  MarketCommentsResponse,
  Session,
  MarketListFilters,
} from "@/lib/api/types";
import { marketListQueryKey } from "@/lib/marketListFilters";

export const queryKeys = {
  marketLists: () => ["markets", "list"] as const,
  markets: (filters: MarketListFilters = {}) =>
    [...queryKeys.marketLists(), marketListQueryKey(filters)] as const,
  market: (id: string) => ["markets", id] as const,
  marketEvents: (id: string) => ["markets", id, "events"] as const,
  marketComments: (id: string) => ["markets", id, "comments"] as const,
  engineStats: (id: string) => ["markets", id, "engine-stats"] as const,
  marketAnalytics: (id: string, interval?: AnalyticsInterval) =>
    [...queryKeys.market(id), "analytics", { interval: interval ?? null }] as const,
  account: (id: string) => ["accounts", id] as const,
  accountRisk: (id: string) => [...queryKeys.account(id), "risk"] as const,
  accountPnl: (id: string) => [...queryKeys.account(id), "pnl"] as const,
  health: () => ["health"] as const,
  serviceIndex: () => ["service-index"] as const,
};

function createEmptyMarketCommentsResponse(marketId: string): MarketCommentsResponse {
  return {
    marketId,
    comments: [],
    pagination: {
      fromSeq: 0,
      limit: 0,
      returned: 0,
      nextFromSeq: null,
    },
    meta: {
      apiVersion: "unknown",
      timestamp: "1970-01-01T00:00:00.000Z",
    },
  };
}

export function useMarkets(filters: MarketListFilters = {}) {
  return useQuery({
    queryKey: queryKeys.markets(filters),
    queryFn: () => api.listMarkets(filters),
    refetchInterval: 5000,
  });
}

export function useMarket(marketId: string, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.market(marketId),
    queryFn: () => api.getMarket(marketId),
    refetchInterval: 5000,
    enabled: opts?.enabled ?? true,
  });
}

export function useMarketEvents(marketId: string) {
  return useQuery({
    queryKey: queryKeys.marketEvents(marketId),
    queryFn: () => api.getMarketEvents(marketId),
  });
}

export function useMarketComments(marketId: string) {
  return useQuery({
    queryKey: queryKeys.marketComments(marketId),
    // Normalize missing mocks or empty responses into the same empty-thread UI state.
    queryFn: async () =>
      (await api.getMarketComments(marketId)) ?? createEmptyMarketCommentsResponse(marketId),
  });
}

export function useEngineStats(marketId: string, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.engineStats(marketId),
    queryFn: () => api.getEngineStats(marketId),
    enabled: opts?.enabled ?? true,
  });
}

export function useMarketAnalytics(
  marketId: string,
  opts?: { enabled?: boolean; interval?: AnalyticsInterval },
) {
  return useQuery({
    queryKey: queryKeys.marketAnalytics(marketId, opts?.interval),
    queryFn: () => api.getMarketAnalytics(marketId, { interval: opts?.interval }),
    enabled: marketId.length > 0 && (opts?.enabled ?? true),
  });
}

export const useAnalytics = useMarketAnalytics;

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: () => api.getHealth(),
    refetchInterval: 10000,
  });
}

export function useServiceIndex() {
  return useQuery({
    queryKey: queryKeys.serviceIndex(),
    queryFn: () => api.getServiceIndex(),
    staleTime: 60000,
  });
}

export function useAccountRisk(accountId: string) {
  return useQuery({
    queryKey: queryKeys.accountRisk(accountId),
    queryFn: () => api.getAccountRisk(accountId),
    enabled: accountId.length > 0,
  });
}

export function useAccountPnl(accountId: string) {
  return useQuery({
    queryKey: queryKeys.accountPnl(accountId),
    queryFn: () => api.getAccountPnl(accountId),
    enabled: accountId.length > 0,
  });
}

export function useCreateMarket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: api.CreateMarketPayload; session?: Session }) =>
      api.createMarket(payload, session),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.marketLists() });
    },
  });
}

export function useProbabilityEdit(marketId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: ProbabilityEditPayload; session: Session }) =>
      api.submitProbabilityEdit(marketId, payload, session),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: queryKeys.market(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.account(variables.payload.accountId) });
    },
  });
}

export function useResolveMarket(marketId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: api.ResolveMarketPayload; session: Session }) =>
      api.resolveMarket(marketId, payload, session),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: queryKeys.market(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.account(variables.payload.accountId) });
      void qc.invalidateQueries({ queryKey: queryKeys.marketLists() });
    },
  });
}

export function useEventTrade(marketId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: EventTradePayload; session: Session }) =>
      api.submitEventTrade(marketId, payload, session),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: queryKeys.market(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.account(variables.payload.accountId) });
    },
  });
}

export function usePostMarketComment(marketId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: CommentPayload; session: Session }) =>
      api.submitMarketComment(marketId, payload, session),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.marketComments(marketId) });
    },
  });
}
