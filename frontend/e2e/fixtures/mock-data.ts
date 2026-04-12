import type {
  MarketListResponse,
  MarketDetailResponse,
  AccountRiskResponse,
  AccountExposureResponse,
  AccountPnlResponse,
  MarketPnlResponse,
  EventTradeResponse,
  MarketEventsResponse,
  MarketCommentsResponse,
  MarketAnalyticsResponse,
  EngineStatsResponse,
} from "../../src/lib/api/types";

const META = { apiVersion: "1.0.0", timestamp: "2026-04-12T00:00:00Z" };

const future = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();

export const ACCOUNT_ID = "test-account-001";
export const AGENT_ID = "test-agent-001";
export const MARKET_ID_1 = "mkt-eth-above-5k";
export const MARKET_ID_2 = "mkt-btc-100k";
export const MARKET_ID_3 = "mkt-sol-launch";

export const marketsResponse: MarketListResponse = {
  markets: [
    {
      id: MARKET_ID_1,
      title: "Will ETH trade above $5000 by December?",
      status: "active",
      liquidity: 25000,
      volume: 12500,
      expires_at: future,
    },
    {
      id: MARKET_ID_2,
      title: "Will BTC reach $100K in 2026?",
      status: "active",
      liquidity: 50000,
      volume: 30000,
      expires_at: future,
    },
    {
      id: MARKET_ID_3,
      title: "Solana mainnet launch on schedule?",
      status: "resolved",
      liquidity: 10000,
      volume: 8000,
      expires_at: "2026-01-01T00:00:00Z",
    },
  ],
  count: 3,
  meta: { ...META, filters: { status: null, include_resolved: false } },
};

export const marketDetailResponse: MarketDetailResponse = {
  market: {
    id: MARKET_ID_1,
    title: "Will ETH trade above $5000 by December?",
    description: "Resolves YES if Ethereum trades above $5000 on any exchange before Dec 31 2026.",
    variableId: MARKET_ID_1,
    status: "active",
    outcomes: [
      { id: "yes", name: "Yes" },
      { id: "no", name: "No" },
    ],
    marginals: { yes: 0.42, no: 0.58 },
    liquidity: 25000,
    volume: 12500,
    created_at: "2026-01-15T12:00:00Z",
    expires_at: future,
  },
  meta: META,
};

export const accountRiskResponse: AccountRiskResponse = {
  account: {
    id: ACCOUNT_ID,
    risk: {
      minAssets: {
        overall: 1250.5,
        markets: [
          {
            marketId: MARKET_ID_1,
            minAsset: 450.25,
            capacityConsumed: 450.25,
            utilization: 0.35,
            commandCount: 5,
            lastOrderId: "ord-001",
            lastCommandId: "cmd-001",
            updatedAt: "2026-04-11T10:00:00Z",
          },
        ],
      },
      capacityIndicators: {
        limit: 5000,
        available: 3749.5,
        consumed: 1250.5,
        utilization: 0.25,
        status: "healthy",
      },
      updatedAt: "2026-04-11T10:00:00Z",
    },
  },
  meta: META,
};

export const accountExposureResponse: AccountExposureResponse = {
  account: {
    id: ACCOUNT_ID,
    exposure: {
      maxPositionSize: 100,
      updatedAt: "2026-04-11T10:00:00Z",
      positions: [
        {
          marketId: MARKET_ID_1,
          outcomeId: "yes",
          netSize: 5.0,
          absSize: 5.0,
          lastTradePrice: 0.42,
          updatedAt: "2026-04-11T10:00:00Z",
          lastOrderId: "ord-001",
          lastCommandId: "cmd-001",
        },
      ],
    },
  },
  meta: META,
};

export const accountPnlResponse: AccountPnlResponse = {
  pnl: {
    accountId: ACCOUNT_ID,
    markets: [
      {
        marketId: MARKET_ID_1,
        outcomes: {
          yes: {
            outcomeId: "yes",
            netSize: 5.0,
            costBasis: 2.1,
            currentValue: 2.5,
            unrealizedPnl: 0.4,
            realizedPnl: 0,
            totalPnl: 0.4,
          },
        },
        summary: {
          totalCostBasis: 2.1,
          totalCurrentValue: 2.5,
          totalUnrealizedPnl: 0.4,
          totalRealizedPnl: 0,
          totalPnl: 0.4,
        },
      },
    ],
    summary: {
      totalCostBasis: 2.1,
      totalCurrentValue: 2.5,
      totalUnrealizedPnl: 0.4,
      totalRealizedPnl: 0,
      totalPnl: 0.4,
    },
  },
  meta: { timestamp: "2026-04-12T00:00:00Z" },
};

export const marketPnlResponse: MarketPnlResponse = {
  pnl: {
    marketId: MARKET_ID_1,
    outcomes: {
      yes: {
        outcomeId: "yes",
        netSize: 5.0,
        costBasis: 2.1,
        currentValue: 2.5,
        unrealizedPnl: 0.4,
        realizedPnl: 0,
        totalPnl: 0.4,
      },
    },
    summary: {
      totalCostBasis: 2.1,
      totalCurrentValue: 2.5,
      totalUnrealizedPnl: 0.4,
      totalRealizedPnl: 0,
      totalPnl: 0.4,
    },
  },
  meta: { timestamp: "2026-04-12T00:00:00Z" },
};

export const eventTradeSuccessResponse: EventTradeResponse = {
  order: {
    id: "ord-new-001",
    type: "EventTrade",
    marketId: MARKET_ID_1,
    accountId: ACCOUNT_ID,
    commandId: "cmd-new-001",
    submittedAt: "2026-04-12T00:01:00Z",
    status: "filled",
    payload: {
      formula: [[{ variableId: MARKET_ID_1, outcomeId: "yes", negated: false }]],
      size: 2,
      side: "buy",
    },
    targetMarketId: MARKET_ID_1,
    targetOutcomeId: "yes",
    side: "buy",
    size: 2,
    price: 0.42,
    notional: 0.84,
    createdAt: "2026-04-12T00:01:00Z",
    filledAt: "2026-04-12T00:01:00Z",
  },
  result: {
    terminal: true,
    status: "accepted",
    eventType: "CommandAccepted",
    eventId: "evt-001",
    commandId: "cmd-new-001",
    emittedAt: "2026-04-12T00:01:00Z",
  },
  meta: { ...META, idempotencyKeyEcho: "idem-key-001" },
};

export const marketEventsResponse: MarketEventsResponse = {
  events: [
    {
      eventId: "evt-genesis",
      marketId: MARKET_ID_1,
      seq: 1,
      type: "MarketCreated",
      prevEventHash: "",
      eventHash: "sha256:abc123def456",
      timestamp: "2026-01-15T12:00:00Z",
      payload: {},
    },
  ],
  meta: META,
};

export const marketCommentsResponse: MarketCommentsResponse = {
  marketId: MARKET_ID_1,
  comments: [],
  pagination: { fromSeq: 0, limit: 50, returned: 0, nextFromSeq: null },
  meta: META,
};

export const marketAnalyticsResponse: MarketAnalyticsResponse = {
  market_id: MARKET_ID_1,
  total_volume: 12500,
  trade_count: 45,
  price_history: [
    { timestamp: "2026-04-10T00:00:00Z", marginals: { yes: 0.4, no: 0.6 } },
    { timestamp: "2026-04-11T00:00:00Z", marginals: { yes: 0.42, no: 0.58 } },
  ],
  top_traders: [{ account_id: ACCOUNT_ID, volume: 500, trade_count: 5 }],
  interval: "1d",
  meta: META,
};

export const engineStatsResponse: EngineStatsResponse = {
  marketId: MARKET_ID_1,
  engine: {
    mode: "jax",
    backend: "cpu",
    version: "1.0.0",
    precision: "float64",
    compile_id: null,
    compile_type: null,
    source_state_hash: null,
  },
  cliques: {
    num_cliques: 1,
    max_clique_size: 2,
    junction_tree_width: 1,
    cliques: [{ id: "c0", nodes: [MARKET_ID_1], size: 2, states: 2 }],
  },
  diagnostics: {
    request_count: 100,
    error_count: 0,
    inference: { p50_ms: 1, p95_ms: 3, p99_ms: 5, mean_ms: 1.5, sample_count: 100 },
    cache: { hits: 80, misses: 20, hit_rate: 0.8 },
  },
  meta: META,
};
