import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api/client";
import type { ProbabilityEditPayload, EventTradePayload, Session } from "@/lib/api/types";

export const queryKeys = {
  markets: (status?: string) => ["markets", { status }] as const,
  market: (id: string) => ["markets", id] as const,
  marketEvents: (id: string) => ["markets", id, "events"] as const,
  engineStats: (id: string) => ["markets", id, "engine-stats"] as const,
  accountRisk: (id: string) => ["accounts", id, "risk"] as const,
  health: () => ["health"] as const,
  serviceIndex: () => ["service-index"] as const,
};

export function useMarkets(status?: string) {
  return useQuery({
    queryKey: queryKeys.markets(status),
    queryFn: () => api.listMarkets(status),
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

export function useEngineStats(marketId: string, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.engineStats(marketId),
    queryFn: () => api.getEngineStats(marketId),
    enabled: opts?.enabled ?? true,
  });
}

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

export function useCreateMarket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: api.CreateMarketPayload; session?: Session }) =>
      api.createMarket(payload, session),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.markets() });
    },
  });
}

export function useProbabilityEdit(marketId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: ProbabilityEditPayload; session: Session }) =>
      api.submitProbabilityEdit(marketId, payload, session),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.market(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.marketEvents(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.engineStats(marketId) });
    },
  });
}

export function useResolveMarket(marketId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: api.ResolveMarketPayload; session: Session }) =>
      api.resolveMarket(marketId, payload, session),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.market(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.marketEvents(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.engineStats(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.markets() });
    },
  });
}

export function useEventTrade(marketId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ payload, session }: { payload: EventTradePayload; session: Session }) =>
      api.submitEventTrade(marketId, payload, session),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.market(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.marketEvents(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.engineStats(marketId) });
    },
  });
}
