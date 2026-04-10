import { useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as api from "@/lib/api/client";
import type {
  ProbabilityEditPayload,
  EventTradePayload,
  CommentPayload,
  Session,
  MarketDetailResponse,
  MarketPriceMessage,
  MarketStatus,
} from "@/lib/api/types";

export const queryKeys = {
  markets: (status?: string) => ["markets", { status }] as const,
  market: (id: string) => ["markets", id] as const,
  marketEvents: (id: string) => ["markets", id, "events"] as const,
  marketComments: (id: string) => ["markets", id, "comments"] as const,
  engineStats: (id: string) => ["markets", id, "engine-stats"] as const,
  accountRisk: (id: string) => ["accounts", id, "risk"] as const,
  accountExposure: (id: string) => ["accounts", id, "exposure"] as const,
  health: () => ["health"] as const,
  serviceIndex: () => ["service-index"] as const,
};

const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 5000;

function invalidateMarketCollectionQueries(qc: QueryClient) {
  return qc.invalidateQueries({
    predicate: ({ queryKey }) => Array.isArray(queryKey)
      && queryKey[0] === "markets"
      && typeof queryKey[1] === "object"
      && queryKey[1] !== null,
  });
}

function invalidateMarketDependentQueries(qc: QueryClient, marketId: string) {
  void qc.invalidateQueries({ queryKey: queryKeys.marketEvents(marketId) });
  void qc.invalidateQueries({ queryKey: queryKeys.engineStats(marketId) });
  void invalidateMarketCollectionQueries(qc);
}

function invalidateAccountExposureQuery(qc: QueryClient, accountId: string) {
  return qc.invalidateQueries({
    queryKey: queryKeys.accountExposure(accountId),
    exact: true,
  });
}

function invalidateAccountExposureQueries(qc: QueryClient) {
  return qc.invalidateQueries({
    predicate: ({ queryKey }) => Array.isArray(queryKey)
      && queryKey.length === 3
      && queryKey[0] === "accounts"
      && typeof queryKey[1] === "string"
      && queryKey[2] === "exposure",
  });
}

function refetchMarketRouteQueries(qc: QueryClient, marketId: string) {
  void qc.invalidateQueries({ queryKey: queryKeys.market(marketId) });
  invalidateMarketDependentQueries(qc, marketId);
}

function isMarketStatus(value: unknown): value is MarketStatus {
  return value === "active" || value === "resolved" || value === "closed" || value === "draft";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseMarginals(value: unknown): Record<string, number> | null {
  if (!isRecord(value)) {
    return null;
  }

  const marginals: Record<string, number> = {};
  for (const [outcomeId, probability] of Object.entries(value)) {
    if (typeof probability !== "number" || !Number.isFinite(probability)) {
      return null;
    }
    marginals[outcomeId] = probability;
  }
  return marginals;
}

function parseMarketPriceMessage(value: unknown): MarketPriceMessage | null {
  if (!isRecord(value)) {
    return null;
  }

  if (
    typeof value.marketId !== "string"
    || !isMarketStatus(value.status)
    || typeof value.seq !== "number"
    || !Number.isFinite(value.seq)
    || typeof value.emittedAt !== "string"
    || typeof value.approxFlag !== "boolean"
  ) {
    return null;
  }

  const marginals = parseMarginals(value.marginals);
  if (!marginals) {
    return null;
  }

  let resolutionProbabilities: Record<string, number> | undefined;
  if (value.resolutionProbabilities != null) {
    const parsedResolutionProbabilities = parseMarginals(value.resolutionProbabilities);
    if (!parsedResolutionProbabilities) {
      return null;
    }
    resolutionProbabilities = parsedResolutionProbabilities;
  }

  return {
    marketId: value.marketId,
    status: value.status,
    marginals,
    seq: value.seq,
    emittedAt: value.emittedAt,
    approxFlag: value.approxFlag,
    resolution: typeof value.resolution === "string" ? value.resolution : undefined,
    resolutionProbabilities,
  };
}

export function useMarketPriceSubscription(marketId: string, opts?: { enabled?: boolean }) {
  const qc = useQueryClient();
  const enabled = opts?.enabled ?? true;
  const lastSeqRef = useRef<number>(-1);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || marketId.length === 0) {
      lastSeqRef.current = -1;
      reconnectAttemptRef.current = 0;
      if (reconnectTimerRef.current != null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      return;
    }

    lastSeqRef.current = -1;
    reconnectAttemptRef.current = 0;

    let socket: WebSocket | null = null;
    let effectClosed = false;
    let terminalStatus: MarketStatus | null = null;

    const clearReconnectTimer = () => {
      if (reconnectTimerRef.current != null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const scheduleReconnect = () => {
      clearReconnectTimer();
      const attempt = reconnectAttemptRef.current;
      const delay = Math.min(
        MAX_RECONNECT_DELAY_MS,
        INITIAL_RECONNECT_DELAY_MS * (2 ** attempt),
      );
      reconnectAttemptRef.current += 1;
      reconnectTimerRef.current = window.setTimeout(() => {
        if (effectClosed || terminalStatus !== null) {
          return;
        }
        refetchMarketRouteQueries(qc, marketId);
        connect();
      }, delay);
    };

    const connect = () => {
      if (effectClosed || terminalStatus !== null) {
        return;
      }

      socket = new WebSocket(api.getMarketPricesWebSocketUrl(marketId));

      socket.addEventListener("open", () => {
        const reconnecting = reconnectAttemptRef.current > 0;
        reconnectAttemptRef.current = 0;
        clearReconnectTimer();
        if (reconnecting) {
          refetchMarketRouteQueries(qc, marketId);
        }
      });

      socket.addEventListener("message", (event) => {
        if (typeof event.data !== "string") {
          return;
        }

        let raw: unknown;
        try {
          raw = JSON.parse(event.data);
        } catch {
          return;
        }

        const update = parseMarketPriceMessage(raw);
        if (!update || update.marketId !== marketId || update.seq <= lastSeqRef.current) {
          return;
        }

        lastSeqRef.current = update.seq;
        qc.setQueryData<MarketDetailResponse>(queryKeys.market(marketId), (current) => {
          if (!current) {
            return current;
          }

          return {
            ...current,
            market: {
              ...current.market,
              status: update.status,
              marginals: update.marginals,
              resolution: update.resolution ?? current.market.resolution,
              resolutionProbabilities: update.resolutionProbabilities ?? current.market.resolutionProbabilities,
            },
          };
        });

        invalidateMarketDependentQueries(qc, marketId);

        if (update.status !== "active") {
          terminalStatus = update.status;
          refetchMarketRouteQueries(qc, marketId);
          socket?.close();
        }
      });

      socket.addEventListener("error", () => {
        socket?.close();
      });

      socket.addEventListener("close", () => {
        socket = null;
        if (effectClosed) {
          return;
        }

        if (terminalStatus !== null) {
          return;
        }

        refetchMarketRouteQueries(qc, marketId);
        scheduleReconnect();
      });
    };

    connect();

    return () => {
      effectClosed = true;
      clearReconnectTimer();
      reconnectAttemptRef.current = 0;
      terminalStatus = null;
      socket?.close();
      socket = null;
    };
  }, [enabled, marketId, qc]);
}

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

export function useMarketComments(marketId: string) {
  return useQuery({
    queryKey: queryKeys.marketComments(marketId),
    queryFn: () => api.getMarketComments(marketId),
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

export function useAccountExposure(accountId: string) {
  return useQuery({
    queryKey: queryKeys.accountExposure(accountId),
    queryFn: () => api.getAccountExposure(accountId),
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
      void invalidateAccountExposureQueries(qc);
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
      void qc.invalidateQueries({ queryKey: queryKeys.marketEvents(marketId) });
      void qc.invalidateQueries({ queryKey: queryKeys.engineStats(marketId) });
      void invalidateAccountExposureQuery(qc, variables.payload.accountId);
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
