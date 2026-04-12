import type {
  MarketListResponse,
  MarketDetailResponse,
  MarketPreviewResponse,
  MarketEventsResponse,
  MarketCommentsResponse,
  EngineStatsResponse,
  MarketAnalyticsResponse,
  AccountRiskResponse,
  AccountExposureResponse,
  OrderResponse,
  EventTradeResponse,
  CommentResponse,
  ApiError,
  CommentPayload,
  ProbabilityEditPayload,
  EventTradePayload,
  Session,
  MarketListFilterInput,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class BayesApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public details: Record<string, unknown> = {},
  ) {
    super(`${code}: ${status}`);
    this.name = "BayesApiError";
  }
}

export interface NormalizedMarketListFilters {
  status?: string;
  includeResolved?: true;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  session?: Session,
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (options.method && ["POST", "PUT", "PATCH"].includes(options.method)) {
    headers["Content-Type"] = "application/json";
  }

  if (session?.agentId) {
    headers["X-Bayes-Agent-Id"] = session.agentId;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  const body = await res.json();

  if (!res.ok) {
    const err = body as ApiError;
    throw new BayesApiError(
      res.status,
      err.error?.code ?? "unknown_error",
      err.error?.details ?? {},
    );
  }

  return body as T;
}

export function normalizeMarketListFilters(
  filters?: MarketListFilterInput,
): NormalizedMarketListFilters {
  const status = typeof filters === "string"
    ? filters
    : filters?.status;
  const includeResolved = (
    typeof filters !== "string"
    && filters?.includeResolved === true
  ) || status === "resolved";

  return {
    ...(status ? { status } : {}),
    ...(includeResolved ? { includeResolved: true } : {}),
  };
}

function serializeMarketListFilters(filters?: MarketListFilterInput): string {
  const normalizedFilters = normalizeMarketListFilters(filters);
  const params = new URLSearchParams();

  if (normalizedFilters.status) {
    params.set("status", normalizedFilters.status);
  }

  if (normalizedFilters.includeResolved) {
    params.set("include_resolved", "true");
  }

  const queryString = params.toString();
  return queryString ? `?${queryString}` : "";
}

export function listMarkets(
  filters?: MarketListFilterInput,
): Promise<MarketListResponse> {
  return request<MarketListResponse>(`/v1/markets${serializeMarketListFilters(filters)}`);
}

export interface CreateMarketPayload {
  title: string;
  description: string;
  outcomes: Array<{ id: string; name: string }>;
  expires_at: string;
  liquidity?: number;
}

export function createMarket(
  payload: CreateMarketPayload,
  session?: Session,
): Promise<MarketDetailResponse> {
  return request<MarketDetailResponse>(`/v1/markets`, {
    method: "POST",
    body: JSON.stringify(payload),
  }, session);
}

export function getMarket(
  marketId: string,
): Promise<MarketDetailResponse> {
  return request<MarketDetailResponse>(`/v1/markets/${encodeURIComponent(marketId)}`);
}

function joinUrlPath(basePath: string, path: string): string {
  const normalizedBase = basePath === "/" ? "" : basePath.replace(/\/$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`;
}

export function getMarketPricesWebSocketUrl(marketId: string): string {
  const baseUrl = API_BASE
    ? new URL(API_BASE, window.location.origin)
    : new URL(window.location.origin);
  const socketUrl = new URL(baseUrl.toString());
  socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
  socketUrl.pathname = joinUrlPath(
    socketUrl.pathname,
    `/ws/markets/${encodeURIComponent(marketId)}/prices`,
  );
  socketUrl.search = "";
  socketUrl.hash = "";
  return socketUrl.toString();
}

export function getMarketEventsWebSocketUrl(marketId: string): string {
  const baseUrl = API_BASE
    ? new URL(API_BASE, window.location.origin)
    : new URL(window.location.origin);
  const socketUrl = new URL(baseUrl.toString());
  socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
  socketUrl.pathname = joinUrlPath(
    socketUrl.pathname,
    `/ws/markets/${encodeURIComponent(marketId)}/events`,
  );
  socketUrl.search = "";
  socketUrl.hash = "";
  return socketUrl.toString();
}

export function getAccountRiskWebSocketUrl(accountId: string): string {
  const baseUrl = API_BASE
    ? new URL(API_BASE, window.location.origin)
    : new URL(window.location.origin);
  const socketUrl = new URL(baseUrl.toString());
  socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
  socketUrl.pathname = joinUrlPath(
    socketUrl.pathname,
    `/ws/accounts/${encodeURIComponent(accountId)}/risk`,
  );
  socketUrl.search = "";
  socketUrl.hash = "";
  return socketUrl.toString();
}

export function getMarketPreview(
  marketId: string,
): Promise<MarketPreviewResponse> {
  return request<MarketPreviewResponse>(`/v1/markets/${encodeURIComponent(marketId)}/meta`);
}

export function getMarketEvents(
  marketId: string,
  opts: { fromSeq?: number; limit?: number } = {},
): Promise<MarketEventsResponse> {
  const params = new URLSearchParams();
  if (opts.fromSeq != null) params.set("fromSeq", String(opts.fromSeq));
  if (opts.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<MarketEventsResponse>(
    `/v1/markets/${encodeURIComponent(marketId)}/events${qs ? `?${qs}` : ""}`,
  );
}

export function getMarketComments(
  marketId: string,
  opts: { fromSeq?: number; limit?: number } = {},
): Promise<MarketCommentsResponse> {
  const params = new URLSearchParams();
  if (opts.fromSeq != null) params.set("fromSeq", String(opts.fromSeq));
  if (opts.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<MarketCommentsResponse>(
    `/v1/markets/${encodeURIComponent(marketId)}/comments${qs ? `?${qs}` : ""}`,
  );
}

export function getEngineStats(
  marketId: string,
): Promise<EngineStatsResponse> {
  return request<EngineStatsResponse>(
    `/v1/markets/${encodeURIComponent(marketId)}/engine-stats`,
  );
}

export function getMarketAnalytics(
  marketId: string,
  interval?: string,
): Promise<MarketAnalyticsResponse> {
  const params = new URLSearchParams();
  if (interval) params.set("interval", interval);
  const qs = params.toString();
  return request<MarketAnalyticsResponse>(
    `/v1/markets/${encodeURIComponent(marketId)}/analytics${qs ? `?${qs}` : ""}`,
  );
}

export function getAccountRisk(
  accountId: string,
): Promise<AccountRiskResponse> {
  return request<AccountRiskResponse>(
    `/v1/accounts/${encodeURIComponent(accountId)}/risk`,
  );
}

export function getAccountExposure(
  accountId: string,
): Promise<AccountExposureResponse> {
  return request<AccountExposureResponse>(
    `/v1/accounts/${encodeURIComponent(accountId)}/exposure`,
  );
}

export function submitProbabilityEdit(
  marketId: string,
  payload: ProbabilityEditPayload,
  session: Session,
): Promise<OrderResponse> {
  return request<OrderResponse>(
    `/v1/markets/${encodeURIComponent(marketId)}/orders/probability-edit`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    session,
  );
}

export interface ResolveMarketPayload {
  accountId: string;
  outcomeId?: string;
  finalProbabilities?: Record<string, number>;
  idempotencyKey?: string;
}

export interface ResolveMarketResponse {
  market: import("./types").Market;
  result: {
    terminal: boolean;
    status: string;
    eventType: string;
    eventId: string;
    commandId: string;
    emittedAt: string;
  };
  meta: import("./types").Meta;
}

export function resolveMarket(
  marketId: string,
  payload: ResolveMarketPayload,
  session: Session,
): Promise<ResolveMarketResponse> {
  return request<ResolveMarketResponse>(
    `/v1/markets/${encodeURIComponent(marketId)}/resolve`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    session,
  );
}

export interface HealthResponse {
  service: string;
  status: string;
  timestamp: string;
}

export interface ServiceIndexResponse {
  service: string;
  status: string;
  routes: Record<string, string[]>;
  meta: import("./types").Meta;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export function getServiceIndex(): Promise<ServiceIndexResponse> {
  return request<ServiceIndexResponse>("/");
}

export function submitEventTrade(
  marketId: string,
  payload: EventTradePayload,
  session: Session,
): Promise<EventTradeResponse> {
  return request<EventTradeResponse>(
    `/v1/markets/${encodeURIComponent(marketId)}/orders/event-trade`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    session,
  );
}

export function submitMarketComment(
  marketId: string,
  payload: CommentPayload,
  session: Session,
): Promise<CommentResponse> {
  return request<CommentResponse>(
    `/v1/markets/${encodeURIComponent(marketId)}/comments`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    session,
  );
}
