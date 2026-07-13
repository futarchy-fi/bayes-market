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

export interface NetMarket {
  id: string;
  variableId: string;
  title: string;
  description?: string;
  status: string;
  outcomes: Array<{ id: string; name: string }>;
  marginals: Record<string, number>;
  parents: string[];
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
  accountId: number;
  total: string;
}

async function request<T>(path: string, options: RequestInit = {}, apiKey?: string): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (apiKey) headers.Authorization = `Bearer ${apiKey}`;

  const response = await fetch(`${EXCHANGE_API}${path}`, { ...options, headers });
  const body = await response.json();
  if (!response.ok) {
    const error = body?.error;
    throw new ExchangeApiError(
      response.status,
      error?.code ?? "unknown_error",
      error?.message ?? `Exchange request failed (${response.status})`,
    );
  }
  return body as T;
}

export const getMe = (apiKey: string) => request<ExchangeAccount>("/v1/me", {}, apiKey);
export const getNetMarket = (marketId: string) =>
  request<NetMarket>(`/v1/net/markets/${encodeURIComponent(marketId)}`);
export const getNetOrders = (apiKey: string) =>
  request<{ orders: NetOrder[] }>("/v1/net/orders/mine", {}, apiKey);
export const getMeNet = (apiKey: string) => request<NetPortfolio>("/v1/me/net", {}, apiKey);
export const getLeaderboard = () => request<{ entries: LeaderboardEntry[] }>("/v1/leaderboard");
export const previewNetEdit = (payload: NetEditPayload, apiKey: string) =>
  request<NetOrderPreview>("/v1/net/orders/preview", { method: "POST", body: JSON.stringify(payload) }, apiKey);
export const placeNetEdit = (payload: NetEditPayload, apiKey: string) =>
  request<PlacedNetOrder>("/v1/net/orders", { method: "POST", body: JSON.stringify(payload) }, apiKey);
