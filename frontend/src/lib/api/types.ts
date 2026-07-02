export interface MarketOutcome {
  id: string;
  name: string;
}

export type MarketStatus = "active" | "resolved" | "closed" | "draft";
export type MarketListStatusFilter = MarketStatus | "all";
export type MarketListSort = "volume" | "liquidity" | "created";

export interface MarketListFilters {
  status?: MarketListStatusFilter;
  sort?: MarketListSort;
  q?: string;
}

export interface MarketSummary {
  id: string;
  title: string;
  status: MarketStatus;
  liquidity: number;
  volume: number;
  expires_at: string;
  /** Engine variable id backing this market; used to map clique/graph node ids. */
  variableId?: string;
  /** Current prices per outcome (kept in sync with the joint market maker). */
  marginals?: Record<string, number>;
}

export interface Market {
  id: string;
  title: string;
  description: string;
  variableId: string;
  status: MarketStatus;
  resolution?: string;
  resolutionProbabilities?: Record<string, number>;
  outcomes: MarketOutcome[];
  marginals: Record<string, number>;
  liquidity: number;
  volume: number;
  created_at: string;
  expires_at: string;
}

export interface MarketListResponse {
  markets: MarketSummary[];
  count: number;
  meta: Meta;
}

export interface MarketDetailResponse {
  market: Market;
  meta: Meta;
}

export interface NetworkNodeSummary {
  marketId: string;
  variableId: string;
  title: string;
  status: MarketStatus;
}

export interface NetworkEdgeSummary {
  from: string;
  to: string;
  fromVariableId: string;
  toVariableId: string;
}

export interface NetworkResponse {
  nodes: NetworkNodeSummary[];
  edges: NetworkEdgeSummary[];
  meta: Meta;
}

export interface MarketPreview {
  marketId: string;
  title: string;
  description: string;
  url: string;
  siteName: string;
  type: string;
}

export interface MarketPreviewResponse {
  preview: MarketPreview;
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

export type AnalyticsInterval = "hour" | "day";

export interface MarketAnalyticsPoint {
  seq: number;
  emittedAt: string;
  probability: number;
}

export interface MarketAnalyticsSeries {
  outcomeId: string;
  outcomeName: string;
  points: MarketAnalyticsPoint[];
}

export interface MarketAnalyticsVolumeBucket {
  bucketStart: string;
  bucketEnd: string;
  tradeCount: number;
  volume: number;
}

export interface MarketAnalyticsTraderRow {
  accountId: string;
  tradeCount: number;
  volume: number;
}

export interface MarketAnalyticsSummary {
  totalTrades: number;
  totalVolume: number;
  uniqueTraders: number;
  bucketInterval: AnalyticsInterval;
  lastUpdated: string;
}

export interface MarketAnalyticsResponse {
  marketId: string;
  summary: MarketAnalyticsSummary;
  priceSeries: MarketAnalyticsSeries[];
  volumeBuckets: MarketAnalyticsVolumeBucket[];
  topTraders: MarketAnalyticsTraderRow[];
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

export interface AccountPnlTotals {
  costBasis: number;
  markedValue: number;
  realizedPnl: number;
  unrealizedPnl: number;
  netPnl: number;
}

export interface AccountPnlPosition {
  marketId: string;
  marketTitle: string;
  marketStatus: Market["status"];
  realizedPnl: number;
  unrealizedPnl: number;
  costBasis: number;
  markedValue: number;
}

export interface AccountPnlResponse {
  account: {
    id: string;
    pnl: {
      totals: AccountPnlTotals;
      positions: AccountPnlPosition[];
      updatedAt: string;
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
  filters?: {
    status?: MarketStatus | null;
    sort?: MarketListSort | null;
    q?: string | null;
  };
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
  side: "buy" | "sell";
  idempotencyKey?: string;
}

export interface CommentPayload {
  accountId: string;
  body: string;
  idempotencyKey?: string;
}

export interface CommentResponse {
  comment: MarketComment;
  meta: Meta & {
    idempotencyKeyEcho?: string;
    replayed?: boolean;
  };
}

export interface Session {
  accountId: string;
  agentId: string;
}

export interface CptParent {
  variableId: string;
  marketId: string | null;
  title: string;
  outcomes: MarketOutcome[];
}

export interface CptEntry {
  contextKey: string;
  context: Array<{ variableId: string; outcomeId: string }>;
  marginals: Record<string, number>;
}

export interface CptResponse {
  marketId: string;
  variableId: string;
  outcomes: MarketOutcome[];
  parents: CptParent[];
  entries: CptEntry[];
  meta: Meta;
}
