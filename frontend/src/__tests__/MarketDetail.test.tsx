import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import MarketDetail from "@/routes/MarketDetail";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useParams: () => ({ marketId: "m1" }) };
});

vi.mock("@/features/session/context", async () => {
  const actual = await vi.importActual<typeof import("@/features/session/context")>(
    "@/features/session/context",
  );
  return {
    ...actual,
    useSession: vi.fn(),
  };
});

vi.mock("@/lib/query/hooks", () => ({
  useMarket: vi.fn(),
  useMarketEvents: vi.fn(),
  useAccountRisk: vi.fn(),
  useMarkets: vi.fn(),
  useMarketComments: vi.fn(),
  usePostMarketComment: vi.fn(),
  useEngineStats: vi.fn(),
  useResolveMarket: vi.fn(),
  useEventTrade: vi.fn(),
  useMarketAnalytics: vi.fn(),
  useAnalytics: vi.fn(),
  useProbabilityEdit: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import {
  useMarket,
  useMarketEvents,
  useAccountRisk,
  useMarkets,
  useMarketComments,
  usePostMarketComment,
  useEngineStats,
  useResolveMarket,
  useEventTrade,
  useProbabilityEdit,
} from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseMarket = vi.mocked(useMarket);
const mockUseMarketEvents = vi.mocked(useMarketEvents);
const mockUseAccountRisk = vi.mocked(useAccountRisk);
const mockUseMarkets = vi.mocked(useMarkets);
const mockUseMarketComments = vi.mocked(useMarketComments);
const mockUsePostMarketComment = vi.mocked(usePostMarketComment);
const mockUseEngineStats = vi.mocked(useEngineStats);
const mockUseResolveMarket = vi.mocked(useResolveMarket);
const mockUseEventTrade = vi.mocked(useEventTrade);
const mockUseProbabilityEdit = vi.mocked(useProbabilityEdit);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function defaultQueryState<T>(data?: T) {
  return {
    data,
    isLoading: false,
    error: null,
    isFetching: false,
    isError: false,
    isSuccess: data !== undefined,
    isPending: false,
    status: (data !== undefined ? "success" : "pending") as "success" | "pending" | "error",
    refetch: vi.fn(),
    fetchStatus: "idle" as const,
    failureCount: 0,
    failureReason: null,
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    isLoadingError: false,
    isFetched: true,
    isFetchedAfterMount: true,
    isInitialLoading: false,
    isPlaceholderData: false,
    isPaused: false,
    isRefetchError: false,
    isRefetching: false,
    isStale: false,
    errorUpdateCount: 0,
    promise: Promise.resolve(data as T),
  } as unknown as ReturnType<typeof useMarket>;
}

function defaultMutationState() {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isSuccess: false,
    isError: false,
    isIdle: true,
    status: "idle" as const,
    data: undefined,
    error: null,
    variables: undefined,
    failureCount: 0,
    failureReason: null,
    submittedAt: 0,
    context: undefined,
  } as unknown as ReturnType<typeof useResolveMarket>;
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockMarket = {
  market: {
    id: "m1",
    title: "ETH Price > $3000 on March 15",
    description: "Will ETH trade above $3000?",
    variableId: "eth_price_gt_3000_mar15",
    status: "active" as const,
    outcomes: [
      { id: "yes", name: "Yes" },
      { id: "no", name: "No" },
    ],
    marginals: { yes: 0.65, no: 0.35 },
    liquidity: 150000,
    volume: 45000,
    created_at: "2026-03-01T00:00:00Z",
    expires_at: "2026-12-31T23:59:59Z",
  },
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

const mockEvents = {
  events: [] as import("@/lib/api/types").MarketEvent[],
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

const mockEngineStats = {
  marketId: "m1",
  engine: { mode: "exact", backend: "junction-tree", version: "1.0", precision: "float64", compile_id: null, compile_type: null, source_state_hash: null },
  cliques: { num_cliques: 0, max_clique_size: 0, junction_tree_width: 0, cliques: [] },
  diagnostics: { request_count: 0, error_count: 0, inference: { p50_ms: 0, p95_ms: 0, p99_ms: 0, mean_ms: 0, sample_count: 0 }, cache: { hits: 0, misses: 0, hit_rate: 0 } },
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

const mockMarketsListData = {
  markets: [{ id: "m1", title: "ETH Price > $3000 on March 15", status: "active" as const, liquidity: 150000, volume: 45000, expires_at: "2026-12-31T23:59:59Z" }],
  count: 1,
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

const mockCommentsData = {
  marketId: "m1",
  comments: [],
  pagination: { fromSeq: 0, limit: 0, returned: 0, nextFromSeq: null },
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

const unconfiguredSession = {
  session: { accountId: "", agentId: "" },
  setAccountId: vi.fn(),
  setAgentId: vi.fn(),
  isConfigured: false,
};

const configuredSession = {
  session: { accountId: "acc-123", agentId: "agent-1" },
  setAccountId: vi.fn(),
  setAgentId: vi.fn(),
  isConfigured: true,
};

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

const FAKE_NOW = new Date("2025-06-01T12:00:00Z");

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(FAKE_NOW);
  vi.clearAllMocks();

  // Default hook return values
  mockUseSession.mockReturnValue(unconfiguredSession);
  mockUseMarket.mockReturnValue(defaultQueryState(mockMarket) as any);
  mockUseMarketEvents.mockReturnValue(defaultQueryState(mockEvents) as any);
  mockUseAccountRisk.mockReturnValue(defaultQueryState(undefined) as any);
  mockUseMarkets.mockReturnValue(defaultQueryState(mockMarketsListData) as any);
  mockUseMarketComments.mockReturnValue(defaultQueryState(mockCommentsData) as any);
  mockUseEngineStats.mockReturnValue(defaultQueryState(mockEngineStats) as any);
  mockUseResolveMarket.mockReturnValue(defaultMutationState() as any);
  mockUseEventTrade.mockReturnValue(defaultMutationState() as any);
  mockUsePostMarketComment.mockReturnValue(defaultMutationState() as any);
  mockUseProbabilityEdit.mockReturnValue(defaultMutationState() as any);
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MarketDetail", () => {
  // ---- Existing tests (refactored to hook-level mocks) ----

  it("renders market title and description", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("ETH Price > $3000 on March 15");
    });
    expect(screen.getByText("Will ETH trade above $3000?")).toBeInTheDocument();
  });

  it("renders status badge", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("active")).toBeInTheDocument();
    });
  });

  it("renders outcome probabilities", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/Yes 65\.0%/)).toBeInTheDocument();
    });
    expect(screen.getByText(/No 35\.0%/)).toBeInTheDocument();
  });

  it("renders assumptions panel for active market", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/Variables & Assumptions/)).toBeInTheDocument();
    });
  });

  it("shows empty events state", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("No events yet.")).toBeInTheDocument();
    });
  });

  it("shows empty discussion state when comments are unavailable", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("No comments yet.")).toBeInTheDocument();
    });
  });

  it("renders junction tree panel", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/Junction Tree & Inference/)).toBeInTheDocument();
    });
  });

  // ---- New tests ----

  it("shows loading spinner when market is loading", () => {
    mockUseMarket.mockReturnValue(
      defaultQueryState(undefined) as any,
    );
    // Override isLoading
    mockUseMarket.mockReturnValue({
      ...defaultQueryState(undefined),
      isLoading: true,
    } as any);

    const { container } = renderWithProviders(<MarketDetail />);
    // LoadingPage renders an SVG spinner
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("shows error message when market fails to load", () => {
    mockUseMarket.mockReturnValue({
      ...defaultQueryState(undefined),
      isLoading: false,
      error: new Error("Market not found"),
      isError: true,
      status: "error",
    } as any);

    renderWithProviders(<MarketDetail />);
    expect(screen.getByText("Market not found")).toBeInTheDocument();
  });

  it("displays Volume, Liquidity, and Expires values", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/Volume:/)).toBeInTheDocument();
    });
    // formatCurrency(45000) = "45.0K", formatCurrency(150000) = "150.0K"
    expect(screen.getByText(/Volume: 45\.0K/)).toBeInTheDocument();
    expect(screen.getByText(/Liquidity: 150\.0K/)).toBeInTheDocument();
    // timeUntil("2026-12-31T23:59:59Z") from 2025-06-01T12:00:00Z ≈ "578d 11h"
    expect(screen.getByText(/Expires: \d+d \d+h/)).toBeInTheDocument();
  });

  it("shows PositionCard when session is configured and risk data exists", async () => {
    mockUseSession.mockReturnValue(configuredSession);
    mockUseAccountRisk.mockReturnValue(defaultQueryState({
      account: {
        id: "acc-123",
        risk: {
          minAssets: {
            overall: 500,
            markets: [
              {
                marketId: "m1",
                minAsset: 123.45,
                capacityConsumed: 50,
                utilization: 0.42,
                commandCount: 7,
                lastOrderId: "ord-1",
                lastCommandId: "cmd-1",
                updatedAt: "2025-06-01T00:00:00Z",
              },
            ],
          },
          capacityIndicators: { limit: 1000, available: 500, consumed: 500, utilization: 0.5, status: "healthy" as const },
          updatedAt: "2025-06-01T00:00:00Z",
        },
      },
      meta: { apiVersion: "1.0", timestamp: "2025-06-01T00:00:00Z" },
    }) as any);

    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("Your Position")).toBeInTheDocument();
    });
    expect(screen.getByText("123.45")).toBeInTheDocument();
    expect(screen.getByText("42.0%")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("hides PositionCard when session is not configured", async () => {
    mockUseSession.mockReturnValue(unconfiguredSession);

    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    });
    expect(screen.queryByText("Your Position")).not.toBeInTheDocument();
  });

  it("renders event table with event rows", async () => {
    const eventsWithData = {
      events: [
        {
          eventId: "evt-1",
          marketId: "m1",
          seq: 1,
          type: "TRADE",
          prevEventHash: "sha256:00000000",
          eventHash: "sha256:aabbccdd11223344",
          timestamp: "2025-06-01T11:30:00Z",
          payload: { side: "buy", amount: 100 },
        },
        {
          eventId: "evt-2",
          marketId: "m1",
          seq: 2,
          type: "RESOLVE",
          prevEventHash: "sha256:aabbccdd11223344",
          eventHash: "sha256:eeff0011aabb2233",
          timestamp: "2025-06-01T11:00:00Z",
          payload: {},
        },
      ],
      meta: { apiVersion: "1.0", timestamp: "2025-06-01T12:00:00Z" },
    };
    mockUseMarketEvents.mockReturnValue(defaultQueryState(eventsWithData) as any);

    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("Seq")).toBeInTheDocument();
    });
    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByText("Hash")).toBeInTheDocument();
    expect(screen.getByText("Time")).toBeInTheDocument();
    // Event data
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText(/TRADE/)).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText(/RESOLVE/)).toBeInTheDocument();
  });

  it("expands and collapses event row payload on click", async () => {
    const eventsWithPayload = {
      events: [
        {
          eventId: "evt-1",
          marketId: "m1",
          seq: 1,
          type: "TRADE",
          prevEventHash: "sha256:00000000",
          eventHash: "sha256:aabbccdd11223344",
          timestamp: "2025-06-01T11:30:00Z",
          payload: { side: "buy", amount: 100 },
        },
      ],
      meta: { apiVersion: "1.0", timestamp: "2025-06-01T12:00:00Z" },
    };
    mockUseMarketEvents.mockReturnValue(defaultQueryState(eventsWithPayload) as any);

    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/TRADE/)).toBeInTheDocument();
    });

    // Payload should not be visible initially
    expect(screen.queryByText(/"side": "buy"/)).not.toBeInTheDocument();

    // Click to expand
    const tradeRow = screen.getByText(/TRADE/).closest("tr")!;
    fireEvent.click(tradeRow);
    expect(screen.getByText(/"side": "buy"/)).toBeInTheDocument();

    // Click again to collapse
    fireEvent.click(tradeRow);
    expect(screen.queryByText(/"side": "buy"/)).not.toBeInTheDocument();
  });

  it("renders ResolveMarketPanel for resolvable market with configured session", async () => {
    mockUseSession.mockReturnValue(configuredSession);

    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("Resolve Market")).toBeInTheDocument();
    });
  });
});
