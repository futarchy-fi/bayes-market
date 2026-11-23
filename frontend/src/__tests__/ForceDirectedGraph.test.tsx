import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { ForceDirectedGraph, MAX_FORCE_NODES } from "@/features/graph/ForceDirectedGraph";
import { EXCHANGE_MODE_KEY } from "@/lib/exchangeMode";
import type { MarketSummary, EngineStatsResponse, Market } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/lib/query/hooks", () => ({
  useNetwork: vi.fn(() => ({ data: undefined })),
  useMarkets: vi.fn(),
  useMarket: vi.fn(),
  useEngineStats: vi.fn(),
  useGraphMarkets: vi.fn(() => ({ data: undefined })),
}));

// Mock the useForceGraph hook to return fixed positions without running D3 simulation
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

// Mock D3 modules to no-ops (zoom/drag attach via useEffect)
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

import { useMarkets, useMarket, useEngineStats, useNetwork } from "@/lib/query/hooks";

const mockUseMarkets = vi.mocked(useMarkets);
const mockUseMarket = vi.mocked(useMarket);
const mockUseEngineStats = vi.mocked(useEngineStats);
const mockUseNetwork = vi.mocked(useNetwork);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mkSummary = (overrides: Partial<MarketSummary> = {}): MarketSummary => ({
  id: "mkt-1",
  title: "Will ETH exceed $3000?",
  status: "active",
  liquidity: 10000,
  volume: 5000,
  expires_at: "2026-12-31T23:59:59Z",
  ...overrides,
});

const mockMarkets: MarketSummary[] = [
  mkSummary({ id: "mkt-1", title: "Will ETH exceed $3000?", status: "active" }),
  mkSummary({ id: "mkt-2", title: "Will BTC hit $100K by year end?", status: "resolved" }),
  mkSummary({
    id: "mkt-3",
    title: "Federal Reserve rate cut before December 2026",
    status: "active",
  }),
];

const mockMarketDetail: Market = {
  id: "mkt-1",
  title: "Will ETH exceed $3000?",
  description: "ETH price market",
  variableId: "var-eth",
  status: "active",
  outcomes: [
    { id: "out-yes", name: "Yes" },
    { id: "out-no", name: "No" },
  ],
  marginals: { "out-yes": 0.75, "out-no": 0.25 },
  liquidity: 10000,
  volume: 5000,
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-12-31T23:59:59Z",
};

const mockEngineStatsData: EngineStatsResponse = {
  marketId: "mkt-1",
  engine: {
    mode: "exact",
    backend: "junction-tree",
    version: "1.0",
    precision: "float64",
    compile_id: null,
    compile_type: null,
    source_state_hash: null,
  },
  cliques: {
    num_cliques: 2,
    max_clique_size: 2,
    junction_tree_width: 3,
    cliques: [
      { id: "c1", nodes: ["mkt-1", "mkt-2"], size: 2, states: 4 },
      { id: "c2", nodes: ["mkt-3"], size: 1, states: 2 },
    ],
  },
  diagnostics: {
    request_count: 100,
    error_count: 0,
    inference: { p50_ms: 1, p95_ms: 3, p99_ms: 5, mean_ms: 1.5, sample_count: 100 },
    cache: { hits: 80, misses: 20, hit_rate: 0.8 },
  },
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

const defaultEdges = [
  { from: "mkt-1", to: "mkt-2" },
  { from: "mkt-2", to: "mkt-3" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function defaultMarketsReturn(overrides: Record<string, unknown> = {}) {
  return {
    data: { markets: mockMarkets, count: mockMarkets.length, meta: { apiVersion: "1.0", timestamp: "t" } },
    isLoading: false,
    isError: false,
    error: null,
    ...overrides,
  } as unknown as ReturnType<typeof useMarkets>;
}

function defaultMarketReturn(market: Market = mockMarketDetail) {
  return {
    data: { market, meta: { apiVersion: "1.0", timestamp: "t" } },
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useMarket>;
}

function defaultEngineStatsReturn(stats: EngineStatsResponse | undefined = undefined) {
  return {
    data: stats,
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useEngineStats>;
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockUseMarkets.mockReturnValue(defaultMarketsReturn());
  mockUseMarket.mockReturnValue(defaultMarketReturn());
  mockUseEngineStats.mockReturnValue(defaultEngineStatsReturn());
  mockUseNetwork.mockReturnValue({ data: undefined } as unknown as ReturnType<typeof useNetwork>);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ForceDirectedGraph", () => {
  it("shows loading message when markets are loading", () => {
    mockUseMarkets.mockReturnValue(
      defaultMarketsReturn({ data: undefined, isLoading: true }),
    );

    renderWithProviders(<ForceDirectedGraph />);
    expect(screen.getByText("Loading network...")).toBeInTheDocument();
  });

  it("shows empty message when no markets exist", () => {
    mockUseMarkets.mockReturnValue(
      defaultMarketsReturn({
        data: { markets: [], count: 0, meta: { apiVersion: "1.0", timestamp: "t" } },
      }),
    );

    renderWithProviders(<ForceDirectedGraph />);
    expect(screen.getByText("No markets to visualize.")).toBeInTheDocument();
  });

  it("renders market node titles with truncation for long names", () => {
    renderWithProviders(<ForceDirectedGraph />);

    expect(screen.getByText("Will ETH exceed $3000?")).toBeInTheDocument();
    expect(screen.getByText("Will BTC hit $100K by year\u2026")).toBeInTheDocument();
    expect(screen.getByText("Federal Reserve rate cut b\u2026")).toBeInTheDocument();
  });

  it("displays the correct variable count in the stats bar", () => {
    renderWithProviders(<ForceDirectedGraph />);
    expect(screen.getByText(/3 variables/)).toBeInTheDocument();
  });

  it("displays edge count when conditionalEdges are provided", () => {
    renderWithProviders(<ForceDirectedGraph conditionalEdges={defaultEdges} />);
    expect(screen.getByText(/2 edges/)).toBeInTheDocument();
  });

  it("displays clique count in stats bar and only renders multi-node clique overlays", () => {
    mockUseEngineStats.mockReturnValue(
      defaultEngineStatsReturn(mockEngineStatsData),
    );

    const { container } = renderWithProviders(
      <ForceDirectedGraph focusMarketId="mkt-1" />,
    );

    expect(screen.getByText(/2 cliques/)).toBeInTheDocument();

    const cliqueLabels = container.querySelectorAll("text");
    const cliqueTexts = Array.from(cliqueLabels)
      .map((el) => el.textContent)
      .filter((t) => t?.startsWith("Clique "));
    expect(cliqueTexts).toEqual(["Clique c1"]);
  });

  it("displays junction tree width when engine stats are available", () => {
    mockUseEngineStats.mockReturnValue(
      defaultEngineStatsReturn(mockEngineStatsData),
    );

    renderWithProviders(<ForceDirectedGraph focusMarketId="mkt-1" />);
    expect(screen.getByText(/JT width 3/)).toBeInTheDocument();
  });

  it("highlights the focused market node with thicker stroke", () => {
    const { container } = renderWithProviders(
      <ForceDirectedGraph focusMarketId="mkt-1" />,
    );

    const nodeRects = container.querySelectorAll('rect[rx="8"]');
    const strokeWidths = Array.from(nodeRects).map((r) =>
      r.getAttribute("stroke-width"),
    );
    expect(strokeWidths.filter((sw) => sw === "2.5")).toHaveLength(1);
    expect(strokeWidths.filter((sw) => sw === "1")).toHaveLength(2);
  });

  it("renders status dots with correct colors for active and resolved markets", () => {
    const { container } = renderWithProviders(<ForceDirectedGraph />);

    const circles = container.querySelectorAll("circle");
    const fills = Array.from(circles).map((c) => c.getAttribute("fill"));
    expect(fills.filter((f) => f === "var(--color-success)")).toHaveLength(2);
    expect(fills.filter((f) => f === "var(--color-info)")).toHaveLength(1);
  });

  describe("legend", () => {
    it("always shows Active and Resolved labels", () => {
      renderWithProviders(<ForceDirectedGraph />);
      expect(screen.getByText("Active")).toBeInTheDocument();
      expect(screen.getByText("Resolved")).toBeInTheDocument();
    });

    it("shows 'Conditional dependency' only when edges are provided", () => {
      const { rerender } = renderWithProviders(<ForceDirectedGraph />);
      expect(screen.queryByText("Conditional dependency")).not.toBeInTheDocument();

      rerender(<ForceDirectedGraph conditionalEdges={defaultEdges} />);
      expect(screen.getByText("Conditional dependency")).toBeInTheDocument();
    });

    it("shows 'Junction tree clique' only when cliques exist", () => {
      renderWithProviders(<ForceDirectedGraph />);
      expect(screen.queryByText("Junction tree clique")).not.toBeInTheDocument();

      mockUseEngineStats.mockReturnValue(
        defaultEngineStatsReturn(mockEngineStatsData),
      );
      renderWithProviders(<ForceDirectedGraph focusMarketId="mkt-1" />);
      expect(screen.getByText("Junction tree clique")).toBeInTheDocument();
    });
  });

  it("renders probability bars directly from loaded markets with zero per-node useMarket calls", () => {
    mockUseMarkets.mockReturnValue(defaultMarketsReturn({
      data: {
        markets: [
          mkSummary({
            id: "mkt-1",
            title: "Will ETH exceed $3000?",
            outcomes: [{ id: "out-yes", name: "Yes" }, { id: "out-no", name: "No" }],
            marginals: { "out-yes": 0.75, "out-no": 0.25 },
          }),
          mkSummary({
            id: "mkt-2",
            title: "Will BTC hit $100K by year end?",
            outcomes: [{ id: "out-btc-yes", name: "Yes" }, { id: "out-btc-no", name: "No" }],
            marginals: { "out-btc-yes": 0.42, "out-btc-no": 0.58 },
          }),
          mkSummary({
            id: "mkt-3",
            title: "Federal Reserve rate cut before December 2026",
            outcomes: [{ id: "out-fed-yes", name: "Cut" }],
            marginals: { "out-fed-yes": 0.6 },
          }),
        ],
        count: 3,
        meta: { apiVersion: "1.0", timestamp: "t" },
      },
    }));

    const { container } = renderWithProviders(<ForceDirectedGraph />);

    expect(mockUseMarket).not.toHaveBeenCalled();
    expect(screen.getByText(/Yes: 75\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/No: 25\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/Yes: 42\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/No: 58\.0%/)).toBeInTheDocument();

    const barRects = container.querySelectorAll('rect[rx="3"]');
    expect(barRects.length).toBeGreaterThanOrEqual(10);
  });

  it("caps rendered nodes at MAX_FORCE_NODES (60) for large networks and never fires per-node useMarket calls", () => {
    const bigMarkets = Array.from({ length: 100 }, (_, i) =>
      mkSummary({ id: `m${i}`, title: `Market ${i}`, marginals: { yes: 0.5, no: 0.5 } }),
    );
    const edges = Array.from({ length: 99 }, (_, i) => ({
      from: `m${i}`,
      to: `m${i + 1}`,
      fromVariableId: `m${i}`,
      toVariableId: `m${i + 1}`,
    }));
    mockUseMarkets.mockReturnValue(defaultMarketsReturn({
      data: { markets: bigMarkets, count: bigMarkets.length, meta: { apiVersion: "1.0", timestamp: "t" } },
    }));
    mockUseNetwork.mockReturnValue({
      data: { nodes: [], edges, meta: { apiVersion: "1.0", timestamp: "t" } },
    } as unknown as ReturnType<typeof useNetwork>);

    const { container } = renderWithProviders(<ForceDirectedGraph focusMarketId="m50" />);

    expect(mockUseMarket).not.toHaveBeenCalled();
    expect(container.querySelectorAll("g[data-node-id]").length).toBe(MAX_FORCE_NODES);
    expect(screen.getByText(`Showing ${MAX_FORCE_NODES} of 100 linked markets`)).toBeInTheDocument();
  });

  it("disables useEngineStats in exchange mode", () => {
    window.localStorage.removeItem(EXCHANGE_MODE_KEY);
    renderWithProviders(<ForceDirectedGraph focusMarketId="mkt-1" />);
    expect(mockUseEngineStats).toHaveBeenCalledWith("mkt-1", { enabled: false });
  });
});
