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

export interface Session {
  accountId: string;
  agentId: string;
}
