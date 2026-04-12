export interface MarketOutcome {
  id: string;
  name: string;
}

export interface MarketSummary {
  id: string;
  title: string;
  status: "active" | "resolved" | "closed" | "draft";
  liquidity: number;
  volume: number;
  expires_at: string;
}

export interface Market {
  id: string;
  title: string;
  description: string;
  variableId: string;
  status: "active" | "resolved" | "closed" | "draft";
  resolution?: string;
  resolutionProbabilities?: Record<string, number>;
  outcomes: MarketOutcome[];
  marginals: Record<string, number>;
  liquidity: number;
  volume: number;
  created_at: string;
  expires_at: string;
}

export type MarketStatus = Market["status"];

export interface MarketListFilters {
  status?: MarketStatus;
  includeResolved?: boolean;
}

export type MarketListFilterInput = MarketListFilters | string;

export interface MarketPriceMessage {
  marketId: string;
  status: MarketStatus;
  marginals: Record<string, number>;
  seq: number;
  emittedAt: string;
  approxFlag: boolean;
  resolution?: string;
  resolutionProbabilities?: Record<string, number>;
  terminalEvent?: {
    eventId?: string;
    eventType?: string;
    commandId?: string;
  };
}

export interface MarketListResponseMeta extends Meta {
  filters: {
    status: MarketStatus | null;
    include_resolved: boolean;
  };
}

export interface MarketListResponse {
  markets: MarketSummary[];
  count: number;
  meta: MarketListResponseMeta;
}

export interface MarketDetailResponse {
  market: Market;
  meta: Meta;
}

export interface MarketPreview {
  marketId: string;
  title: string;
  description: string;
  url: string;
  siteName: string;
  type: string;
  outcomes?: Array<{ id: string; name: string; probability: number }>;
}

export interface MarketPreviewResponse {
  preview: MarketPreview;
  meta: Meta;
}

export interface PriceHistoryEntry {
  timestamp: string;
  marginals: Record<string, number>;
}

export interface TopTrader {
  account_id: string;
  volume: number;
  trade_count: number;
}

export interface MarketAnalyticsResponse {
  market_id: string;
  total_volume: number;
  trade_count: number;
  price_history: PriceHistoryEntry[];
  top_traders: TopTrader[];
  interval: string;
  meta: Meta;
}

export interface MarketEvent {
  eventId: string;
  marketId: string;
  seq: number;
  type: string;
  prevEventHash: string;
  eventHash: string;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface MarketEventsResponse {
  events: MarketEvent[];
  meta: Meta;
}

export interface MarketComment {
  commentId: string;
  marketId: string;
  seq: number;
  accountId: string;
  body: string;
  createdAt: string;
}

export interface PaginatedCollection {
  fromSeq: number;
  limit: number;
  returned: number;
  nextFromSeq: number | null;
}

export interface MarketCommentsResponse {
  marketId: string;
  comments: MarketComment[];
  pagination: PaginatedCollection;
  meta: Meta;
}

export interface EngineInfo {
  mode: string;
  backend: string;
  version: string;
  precision: string;
  compile_id: string | null;
  compile_type: string | null;
  source_state_hash: string | null;
}

export interface CliqueSummary {
  id: string;
  nodes: string[];
  size: number;
  states: number;
}

export interface EngineStatsResponse {
  marketId: string;
  engine: EngineInfo;
  cliques: {
    num_cliques: number;
    max_clique_size: number;
    junction_tree_width: number;
    cliques: CliqueSummary[];
  };
  diagnostics: {
    request_count: number;
    error_count: number;
    inference: {
      p50_ms: number;
      p95_ms: number;
      p99_ms: number;
      mean_ms: number;
      sample_count: number;
    };
    cache: {
      hits: number;
      misses: number;
      hit_rate: number;
    };
    compile_time_ms?: number;
    memory_bytes?: number;
    last_updated?: string;
  };
  meta: Meta;
}

export interface MarketRisk {
  marketId: string;
  minAsset: number;
  capacityConsumed: number;
  utilization: number;
  commandCount: number;
  lastOrderId: string;
  lastCommandId: string;
  updatedAt: string;
}

export interface CapacityIndicators {
  limit: number;
  available: number;
  consumed: number;
  utilization: number;
  status: "healthy" | "warning" | "critical";
}

export interface AccountRiskResponse {
  account: {
    id: string;
    risk: {
      minAssets: {
        overall: number;
        markets: MarketRisk[];
      };
      capacityIndicators: CapacityIndicators;
      updatedAt: string;
    };
  };
  meta: Meta;
}

export interface AccountExposurePosition {
  marketId: string;
  outcomeId: string;
  netSize: number;
  absSize: number;
  lastTradePrice: number;
  updatedAt: string;
  lastOrderId: string | null;
  lastCommandId: string | null;
}

export interface AccountExposureResponse {
  account: {
    id: string;
    exposure: {
      maxPositionSize: number;
      updatedAt: string;
      positions: AccountExposurePosition[];
    };
  };
  meta: Meta;
}

export interface AssetDelta {
  beforeMinAsset: number;
  afterMinAsset: number;
  impactScore: number;
  riskLimit: number;
}

export interface TerminalOutcome {
  status: "accepted" | "rejected";
  reason?: string;
  code?: string;
}

export interface OrderResponse {
  command: {
    commandId: string;
    marketId: string;
    accountId: string;
    type: string;
    submittedAt: string;
  };
  order: {
    orderId: string;
    commandId: string;
    marketId: string;
    type: string;
  };
  assetDelta: AssetDelta;
  terminalOutcome: TerminalOutcome;
  meta: Meta;
}

export interface AcceptedTerminalResult {
  terminal: true;
  status: "accepted";
  eventType: "CommandAccepted";
  eventId: string;
  commandId: string;
  emittedAt: string;
}

export interface CommandResponseMeta extends Meta {
  idempotencyKeyEcho?: string;
  replayed?: boolean;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  meta: Meta;
}

export interface Meta {
  apiVersion: string;
  timestamp: string;
}

export interface ProbabilityEditPayload {
  accountId: string;
  variableId: string;
  target: {
    kind: "marginal";
    outcomeId: string;
    probability: number;
  };
  context: Array<{ variableId: string; outcomeId: string }>;
  idempotencyKey?: string;
}

export interface EventTradePayload {
  accountId: string;
  formula: Array<Array<{ variableId: string; outcomeId: string; negated: boolean }>>;
  size: number;
  side: "buy" | "sell";
  idempotencyKey?: string;
}

export interface EventTradeOrderPayload {
  formula: EventTradePayload["formula"];
  size: EventTradePayload["size"];
  side: EventTradePayload["side"];
}

export interface EventTradeOrder {
  id: string;
  type: "EventTrade";
  marketId: string;
  accountId: string;
  commandId: string;
  submittedAt: string;
  status: "filled";
  payload: EventTradeOrderPayload;
  targetMarketId: string;
  targetOutcomeId: string;
  side: EventTradePayload["side"];
  size: EventTradePayload["size"];
  price: number;
  notional: number;
  createdAt: string;
  filledAt: string;
  idempotencyKey?: string;
}

export interface EventTradeResponse {
  order: EventTradeOrder;
  result: AcceptedTerminalResult;
  meta: CommandResponseMeta;
}

export interface CommentPayload {
  accountId: string;
  body: string;
  idempotencyKey?: string;
}

export interface CommentResponse {
  comment: MarketComment;
  meta: CommandResponseMeta;
}

export interface MarketEventMessage {
  type: "snapshot" | "event";
  marketId: string;
  event?: MarketEvent;
  events?: MarketEvent[];
  seq: number;
  emittedAt: string;
}

export interface AccountRiskMessage {
  type: "snapshot" | "risk";
  accountId: string;
  risk: {
    accountId: string;
    riskLimit: number;
    minAsset: number;
    updatedAt: string;
    markets: Record<string, MarketRisk>;
  } | null;
  exposure: {
    accountId: string;
    updatedAt: string;
    positions: Record<string, AccountExposurePosition>;
  } | null;
  seq: number;
  emittedAt: string;
}

export interface Session {
  accountId: string;
  agentId: string;
}
