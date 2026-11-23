export const EXCHANGE_API = import.meta.env.VITE_EXCHANGE_API ?? "https://api.futarchy.ai";

export class ExchangeApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ExchangeApiError";
  }
}

export interface ExchangeAccount {
  account_id: number;
  available: string;
  frozen: string;
  total: string;
  locks: Array<{ lock_id: number; market_id: number; amount: string; lock_type: string }>;
}

export interface ExchangeHealthResponse {
  status: string;
  markets?: number;
  ledger_accounts?: number;
  users?: number;
  net?: { markets: number; orders: number; enabled: boolean };
  venues?: Record<string, { markets: number; orders_or_trades: number }>;
}

export interface NetMarket {
  id: string;
  variableId: string;
  title: string;
  description?: string;
  status: string;
  outcomes: Array<{ id: string; name: string }>;
  marginals: Record<string, number>;
  parents: string[];
  volume?: number;
  liquidity?: number;
}

export interface NetMarketList {
  markets: NetMarket[];
  count: number;
}

export interface NetMarginalResponse {
  variable: string;
  context: Record<string, string>;
  marginal: Record<string, number>;
}

export interface NetEditPayload {
  variableId: string;
  outcomeId: string;
  target: number;
  context?: Record<string, string>;
}

export interface NetOrderPreview {
  stake: string;
  before: number;
  after: number;
  b: string;
}

export interface NetOrder {
  orderId: string;
  accountId: number;
  variableId: string;
  outcomeId: string;
  target: number;
  context: Record<string, string>;
  before: number;
  after: number;
  stake: string;
  lockId: number;
  status: string;
  fill: Record<string, number>;
  remainingContext: Record<string, string>;
}

export interface PlacedNetOrder extends NetOrder {
  balance: { available: string; frozen: string };
}

export interface NetPortfolio {
  orders: NetOrder[];
  openStake: string;
  settledPnl: string;
}

export interface LeaderboardEntry {
  login: string | null;
  displayName?: string | null;
  accountId: number;
  total: string;
  netOrders?: number;
  netVolume?: string;
}

export type Venue = "net" | "amm" | "book";

export interface InstrumentListing {
  venue: Venue;
  marketId: string;
  yesPrice: number | null;
  status: string;
}

export interface Instrument {
  instrumentId: string;
  title: string;
  listings: InstrumentListing[];
}

export interface MarketResolver {
  type: string;
  repo?: string;
  pr_number?: number;
}

export interface MarketMetadata extends Record<string, unknown> {
  creator_account_id?: number;
  creator_github_id?: number;
  creator_login?: string;
  resolution_criteria?: string;
  resolution_rules?: string;
}

export interface AmmMarket {
  market_id: number;
  question: string;
  status: string;
  outcomes: string[];
  prices: Record<string, string>;
  creator_account_id?: number | null;
  resolver?: MarketResolver;
  metadata?: MarketMetadata;
}

export interface AmmTradePayload {
  outcome: string;
  budget?: string;
  amount?: string;
}

export interface AmmTradeResult {
  trade_id: number;
  outcome: string;
  amount: string;
  price: string;
  value: string;
}

export interface BookMarket {
  id: number;
  question: string;
  status: string;
  outcomes: string[];
  bestBid: string | null;
  bestAsk: string | null;
  lastPrice: string | null;
  creatorAccountId?: number | null;
  resolver?: MarketResolver;
  metadata?: MarketMetadata;
}

export interface BookDepthLevel { price: string; size: string }
export interface BookOutcomeDepth { bids: BookDepthLevel[]; asks: BookDepthLevel[] }
export interface BookDepth extends BookOutcomeDepth {
  marketId: number;
  outcomes: Record<string, BookOutcomeDepth>;
}

export interface BookOrderPayload {
  marketId: number;
  side: "bid" | "ask";
  outcome: string;
  price: string;
  size: string;
}

export interface BookOrder extends BookOrderPayload {
  orderId: number;
  accountId: number;
  filled: string;
  remaining: string;
  status: string;
  createdAt: string;
}

export interface PlacedBookOrder extends BookOrder {
  balance: { available: string; frozen: string };
}

export interface BookPosition { marketId: number; yes: string; no: string }

export const EXCHANGE_UNAUTHORIZED_EVENT = "exchange:unauthorized";

export interface ExchangeUnauthorizedDetail {
  apiKey: string;
  error: ExchangeApiError;
}

type UnauthorizedListener = (apiKey: string, error: ExchangeApiError) => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

export function onExchangeUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

function notifyUnauthorized(apiKey: string, error: ExchangeApiError) {
  for (const listener of unauthorizedListeners) {
    try {
      listener(apiKey, error);
    } catch {
      // Never let a listener exception mask the underlying API error.
    }
  }
  if (typeof window !== "undefined" && typeof CustomEvent === "function") {
    try {
      window.dispatchEvent(
        new CustomEvent<ExchangeUnauthorizedDetail>(EXCHANGE_UNAUTHORIZED_EVENT, {
          detail: { apiKey, error },
        }),
      );
    } catch {
      // Ignore event dispatch failures in restricted environments.
    }
  }
}

async function readResponseBody(response: Response): Promise<{ parsed: unknown; rawText: string }> {
  if (typeof response.text === "function") {
    const rawText = await response.text();
    if (!rawText.trim()) return { parsed: null, rawText };
    try {
      return { parsed: JSON.parse(rawText), rawText };
    } catch {
      return { parsed: null, rawText };
    }
  }
  if (typeof response.json === "function") {
    try {
      const parsed = await response.json();
      return { parsed, rawText: "" };
    } catch {
      return { parsed: null, rawText: "" };
    }
  }
  return { parsed: null, rawText: "" };
}

function fallbackErrorMessage(status: number, rawText: string): string {
  const trimmed = rawText.trim();
  if (trimmed && !trimmed.startsWith("<") && trimmed.length <= 200) {
    return trimmed;
  }
  return `Exchange request failed (${status})`;
}

async function request<T>(path: string, options: RequestInit = {}, apiKey?: string): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  const response = await fetch(`${EXCHANGE_API}${path}`, { ...options, headers });
  const { parsed, rawText } = await readResponseBody(response);

  if (!response.ok) {
    const error =
      parsed && typeof parsed === "object" && "error" in parsed
        ? (parsed as { error?: { code?: string; message?: string } }).error
        : undefined;
    const code = error?.code ?? (response.status === 401 ? "auth_required" : "unknown_error");
    const message = error?.message ?? fallbackErrorMessage(response.status, rawText);
    const apiError = new ExchangeApiError(response.status, code, message);
    if (apiKey && response.status === 401) {
      notifyUnauthorized(apiKey, apiError);
    }
    throw apiError;
  }

  if (response.status === 204 || (parsed === null && !rawText.trim())) {
    return undefined as T;
  }

  if (parsed === null) {
    throw new ExchangeApiError(
      response.status,
      "invalid_response",
      "Exchange returned an unexpected non-JSON response.",
    );
  }

  return parsed as T;
}

/** Best-effort server-side session revocation; ignores network or HTTP errors. */
export async function logoutExchange(apiKey: string): Promise<void> {
  if (!apiKey || typeof fetch !== "function") return;
  try {
    await fetch(`${EXCHANGE_API}/v1/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}` },
    });
  } catch {
    // Ignore network errors during best-effort logout.
  }
}

export const getExchangeHealth = () => request<ExchangeHealthResponse>("/v1/health");
export const getMe = (apiKey: string) => request<ExchangeAccount>("/v1/me", {}, apiKey);
export const getNetMarket = (marketId: string) =>
  request<NetMarket>(`/v1/net/markets/${encodeURIComponent(marketId)}`);
export const getNetMarkets = () => request<NetMarketList>("/v1/net/markets");
export const getNetMarginal = (variableId: string, context: Record<string, string>) => {
  const params = new URLSearchParams({ variable: variableId });
  if (Object.keys(context).length > 0) {
    params.set("context", Object.entries(context).map(([key, value]) => `${key}=${value}`).join("|"));
  }
  return request<NetMarginalResponse>(`/v1/net/marginal?${params.toString()}`);
};
export const getNetNetwork = () =>
  request<import("@/lib/api/types").NetworkResponse>("/v1/net/network");
export const getNetGraphMarkets = (context: Array<{ variableId: string; outcomeId: string }> = []) => {
  const params = new URLSearchParams({ fields: "graph" });
  if (context.length > 0) {
    params.set("context", context.map(({ variableId, outcomeId }) => `${variableId}=${outcomeId}`).join("|"));
  }
  return request<import("@/lib/api/types").GraphMarketsResponse>(`/v1/net/markets?${params.toString()}`);
};
export const getNetOrders = (apiKey: string) =>
  request<{ orders: NetOrder[] }>("/v1/net/orders/mine", {}, apiKey);
export const getMeNet = (apiKey: string) => request<NetPortfolio>("/v1/me/net", {}, apiKey);
export const getLeaderboard = () => request<{ entries: LeaderboardEntry[] }>("/v1/leaderboard");
export const getInstruments = () => request<Instrument[]>("/v1/instruments");
export const getAmmMarket = (marketId: string) => request<AmmMarket>(`/v1/markets/${encodeURIComponent(marketId)}`);
export const tradeAmm = (marketId: string, action: "buy" | "sell", payload: AmmTradePayload, apiKey: string) =>
  request<AmmTradeResult>(`/v1/markets/${encodeURIComponent(marketId)}/${action}`, { method: "POST", body: JSON.stringify(payload) }, apiKey);
export const getBookMarket = (marketId: string) => request<BookMarket>(`/v1/book/markets/${encodeURIComponent(marketId)}`);
export const getBookDepth = (marketId: string) => request<BookDepth>(`/v1/book/markets/${encodeURIComponent(marketId)}/orderbook`);
export const getBookOrders = (apiKey: string) => request<{ orders: BookOrder[] }>("/v1/book/orders/mine", {}, apiKey);
export const getBookPositions = (apiKey: string) => request<{ positions: BookPosition[] }>("/v1/book/positions/mine", {}, apiKey);
export const placeBookOrder = (payload: BookOrderPayload, apiKey: string) =>
  request<PlacedBookOrder>("/v1/book/orders", { method: "POST", body: JSON.stringify(payload) }, apiKey);
export const cancelBookOrder = (orderId: number, apiKey: string) =>
  request<PlacedBookOrder>(`/v1/book/orders/${orderId}`, { method: "DELETE" }, apiKey);
export const previewNetEdit = (payload: NetEditPayload, apiKey: string) =>
  request<NetOrderPreview>("/v1/net/orders/preview", { method: "POST", body: JSON.stringify(payload) }, apiKey);
export const placeNetEdit = (payload: NetEditPayload, apiKey: string) =>
  request<PlacedNetOrder>("/v1/net/orders", { method: "POST", body: JSON.stringify(payload) }, apiKey);
