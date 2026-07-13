import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as exchange from "./client";
import { useExchangeSession } from "./session";

export const exchangeQueryKeys = {
  me: () => ["exchange", "me"] as const,
  market: (id: string) => ["exchange", "markets", id] as const,
  orders: () => ["exchange", "orders"] as const,
  portfolio: () => ["exchange", "portfolio"] as const,
  leaderboard: () => ["exchange", "leaderboard"] as const,
  instruments: () => ["exchange", "instruments"] as const,
  ammMarket: (id: string) => ["exchange", "amm", "markets", id] as const,
  bookMarket: (id: string) => ["exchange", "book", "markets", id] as const,
  bookDepth: (id: string) => ["exchange", "book", "depth", id] as const,
  bookOrders: () => ["exchange", "book", "orders"] as const,
  bookPositions: () => ["exchange", "book", "positions"] as const,
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

export function useInstruments() {
  return useQuery({ queryKey: exchangeQueryKeys.instruments(), queryFn: exchange.getInstruments, refetchInterval: 10000 });
}

export function useAmmMarket(marketId: string) {
  return useQuery({ queryKey: exchangeQueryKeys.ammMarket(marketId), queryFn: () => exchange.getAmmMarket(marketId), enabled: Boolean(marketId), refetchInterval: 10000 });
}

export function useTradeAmm(marketId: string) {
  const { session } = useExchangeSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ action, payload }: { action: "buy" | "sell"; payload: exchange.AmmTradePayload }) => exchange.tradeAmm(marketId, action, payload, session.apiKey),
    onSuccess: () => Promise.all([
      queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.me() }),
      queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.ammMarket(marketId) }),
      queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.instruments() }),
    ]),
  });
}

export function useBookMarket(marketId: string) {
  return useQuery({ queryKey: exchangeQueryKeys.bookMarket(marketId), queryFn: () => exchange.getBookMarket(marketId), enabled: Boolean(marketId), refetchInterval: 10000 });
}

export function useBookDepth(marketId: string) {
  return useQuery({ queryKey: exchangeQueryKeys.bookDepth(marketId), queryFn: () => exchange.getBookDepth(marketId), enabled: Boolean(marketId), refetchInterval: 5000 });
}

export function useBookOrders() {
  const { session, isSignedIn } = useExchangeSession();
  return useQuery({ queryKey: [...exchangeQueryKeys.bookOrders(), session.githubLogin], queryFn: () => exchange.getBookOrders(session.apiKey), enabled: isSignedIn, refetchInterval: 10000 });
}

export function useBookPositions() {
  const { session, isSignedIn } = useExchangeSession();
  return useQuery({ queryKey: [...exchangeQueryKeys.bookPositions(), session.githubLogin], queryFn: () => exchange.getBookPositions(session.apiKey), enabled: isSignedIn, refetchInterval: 10000 });
}

function invalidateBook(queryClient: ReturnType<typeof useQueryClient>, marketId?: string) {
  void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.me() });
  void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.bookOrders() });
  void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.bookPositions() });
  if (marketId) {
    void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.bookMarket(marketId) });
    void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.bookDepth(marketId) });
  }
  void queryClient.invalidateQueries({ queryKey: exchangeQueryKeys.instruments() });
}

export function usePlaceBookOrder(marketId: string) {
  const { session } = useExchangeSession();
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: (payload: exchange.BookOrderPayload) => exchange.placeBookOrder(payload, session.apiKey), onSuccess: () => invalidateBook(queryClient, marketId) });
}

export function useCancelBookOrder(marketId?: string) {
  const { session } = useExchangeSession();
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: (orderId: number) => exchange.cancelBookOrder(orderId, session.apiKey), onSuccess: () => invalidateBook(queryClient, marketId) });
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
