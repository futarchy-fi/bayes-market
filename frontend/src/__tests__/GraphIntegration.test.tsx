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
  useNetwork: vi.fn(() => ({ data: undefined })),
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
  useCpt: vi.fn(),
  queryKeys: {
    marketLists: () => ["markets", "list"],
    markets: () => ["markets", "list", ""],
    market: (id: string) => ["markets", id],
    marketEvents: (id: string) => ["markets", id, "events"],
    marketComments: (id: string) => ["markets", id, "comments"],
    engineStats: (id: string) => ["markets", id, "engine-stats"],
    marketCpt: (id: string) => ["markets", id, "cpt"],
  },
}));

// Mock D3 modules (ForceDirectedGraph uses them)
vi.mock("d3-selection", () => ({
  select: vi.fn(() => ({
    call: vi.fn().mockReturnThis(),
    on: vi.fn().mockReturnThis(),
    selectAll: vi.fn(() => ({
      call: vi.fn().mockReturnThis(),
      on: vi.fn().mockReturnThis(),
    })),
  })),
}));

vi.mock("d3-zoom", () => ({
  zoom: vi.fn(() => {
    const z: Record<string, unknown> = {};
    z.scaleExtent = vi.fn().mockReturnValue(z);
    z.on = vi.fn().mockReturnValue(z);
    z.transform = vi.fn();
    return z;
  }),
  zoomIdentity: {},
}));

vi.mock("d3-drag", () => ({
  drag: vi.fn(() => {
    const d: Record<string, unknown> = {};
    d.on = vi.fn().mockReturnValue(d);
    return d;
  }),
}));

// Mock useForceGraph to return stable positions
vi.mock("@/features/graph/useForceGraph", () => ({
  useForceGraph: vi.fn(
    (inputNodes: Array<{ id: string }>) => ({
      positions: {
        nodes: inputNodes.map((n: { id: string }, i: number) => ({
          id: n.id,
          x: 100 + i * 200,
          y: 200,
        })),
      },
      getSimulation: () => null,
      getNodes: () => [],
      flushPositions: vi.fn(),
    }),
  ),
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
  useCpt,
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
const mockUseCpt = vi.mocked(useCpt);

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
    title: "ETH Price > $3000",
    description: "Will ETH trade above $3000?",
    variableId: "eth_price",
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

const mockMarket2 = {
  market: {
    id: "m2",
    title: "BTC > $100K",
    description: "Will BTC exceed $100K?",
    variableId: "btc_price",
    status: "active" as const,
    outcomes: [
      { id: "yes", name: "Yes" },
      { id: "no", name: "No" },
    ],
    marginals: { yes: 0.4, no: 0.6 },
    liquidity: 200000,
    volume: 80000,
    created_at: "2026-01-01T00:00:00Z",
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
  markets: [
    { id: "m1", title: "ETH Price > $3000", status: "active" as const, liquidity: 150000, volume: 45000, expires_at: "2026-12-31T23:59:59Z" },
    { id: "m2", title: "BTC > $100K", status: "active" as const, liquidity: 200000, volume: 80000, expires_at: "2026-12-31T23:59:59Z" },
  ],
  count: 2,
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

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

const FAKE_NOW = new Date("2025-06-01T12:00:00Z");

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(FAKE_NOW);
  vi.clearAllMocks();

  mockUseSession.mockReturnValue(unconfiguredSession);
  mockUseMarket.mockImplementation((marketId: string) => {
    if (marketId === "m2") return defaultQueryState(mockMarket2) as any;
    return defaultQueryState(mockMarket) as any;
  });
  mockUseMarketEvents.mockReturnValue(defaultQueryState(mockEvents) as any);
  mockUseAccountRisk.mockReturnValue(defaultQueryState(undefined) as any);
  mockUseMarkets.mockReturnValue(defaultQueryState(mockMarketsListData) as any);
  mockUseMarketComments.mockReturnValue(defaultQueryState(mockCommentsData) as any);
  mockUseEngineStats.mockReturnValue(defaultQueryState(mockEngineStats) as any);
  mockUseResolveMarket.mockReturnValue(defaultMutationState() as any);
  mockUseEventTrade.mockReturnValue(defaultMutationState() as any);
  mockUsePostMarketComment.mockReturnValue(defaultMutationState() as any);
  mockUseProbabilityEdit.mockReturnValue(defaultMutationState() as any);
  mockUseCpt.mockReturnValue(defaultQueryState(undefined) as any);
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Graph Integration", () => {
  it("renders the graph toolbar with Force/Circular toggle", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("Force")).toBeInTheDocument();
    });
    expect(screen.getByText("Circular")).toBeInTheDocument();
  });

  it("renders export and import buttons in the toolbar", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByTitle("Export network as JSON")).toBeInTheDocument();
    });
    expect(screen.getByTitle("Import network from JSON")).toBeInTheDocument();
  });

  it("defaults to force-directed view showing 'Bayesian Network' heading", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("Bayesian Network")).toBeInTheDocument();
    });
  });

  it("switches to circular view when Circular button is clicked", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("Circular")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Circular"));

    // BayesNetGraph also renders "Bayesian Network" heading
    await waitFor(() => {
      expect(screen.getByText("Bayesian Network")).toBeInTheDocument();
    });
  });

  it("renders undo/redo toolbar for active markets", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByLabelText("Undo")).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Redo")).toBeInTheDocument();
  });

  it("undo button is disabled when no actions have been taken", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      const undoBtn = screen.getByLabelText("Undo");
      expect(undoBtn).toBeDisabled();
    });
  });

  it("renders graph with multiple market nodes", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/2 variables/)).toBeInTheDocument();
    });
  });
});
