import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as exchange from "./client";
import { useExchangeSession } from "./session";

export const exchangeQueryKeys = {
  me: () => ["exchange", "me"] as const,
  market: (id: string) => ["exchange", "markets", id] as const,
  orders: () => ["exchange", "orders"] as const,
  portfolio: () => ["exchange", "portfolio"] as const,
  leaderboard: () => ["exchange", "leaderboard"] as const,
};

export function useExchangeMe() {
  const { session, isSignedIn } = useExchangeSession();
  return useQuery({
    queryKey: [...exchangeQueryKeys.me(), session.githubLogin],
    queryFn: () => exchange.getMe(session.apiKey),
    enabled: isSignedIn,
    refetchInterval: 15000,
  });
}

export function useNetMarket(marketId: string, enabled = true) {
  return useQuery({
    queryKey: exchangeQueryKeys.market(marketId),
    queryFn: () => exchange.getNetMarket(marketId),
    enabled: Boolean(marketId) && enabled,
    refetchInterval: 15000,
  });
}

export function useNetOrders() {
  const { session, isSignedIn } = useExchangeSession();
  return useQuery({
    queryKey: [...exchangeQueryKeys.orders(), session.githubLogin],
    queryFn: () => exchange.getNetOrders(session.apiKey),
    enabled: isSignedIn,
  });
}

export function useMeNet() {
  const { session, isSignedIn } = useExchangeSession();
  return useQuery({
    queryKey: [...exchangeQueryKeys.portfolio(), session.githubLogin],
    queryFn: () => exchange.getMeNet(session.apiKey),
    enabled: isSignedIn,
  });
}

export function useLeaderboard() {
  return useQuery({
    queryKey: exchangeQueryKeys.leaderboard(),
    queryFn: exchange.getLeaderboard,
    refetchInterval: 15000,
  });
}

export function usePreviewNetEdit() {
  const { session } = useExchangeSession();
  return useMutation({ mutationFn: (payload: exchange.NetEditPayload) => exchange.previewNetEdit(payload, session.apiKey) });
}

export function usePlaceNetEdit(marketId: string) {
  const { session } = useExchangeSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: exchange.NetEditPayload) => exchange.placeNetEdit(payload, session.apiKey),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.me() });
      void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.market(marketId) });
      void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.orders() });
      void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.portfolio() });
      void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.leaderboard() });
    },
  });
}
