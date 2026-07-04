import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { BeliefFlowGraph } from "@/features/graph/BeliefFlowGraph";

// ---------------------------------------------------------------------------
// Regression test for the >AUTO_FOCUS_NODE_LIMIT mount storm: with a large
// market set, BeliefFlowGraph used to mount one FlowNode (and fire its two
// useMarket queries) per market on the FIRST commit, then prune down to the
// ego subgraph only after a subsequent effect fired. This asserts the first
// (and only) commit already respects the hard render cap.
// ---------------------------------------------------------------------------

vi.mock("@/lib/query/hooks", () => ({
  useMarkets: vi.fn(),
  useMarket: vi.fn(),
  useNetwork: vi.fn(),
}));

import { useMarkets, useMarket, useNetwork } from "@/lib/query/hooks";

const mockUseMarkets = vi.mocked(useMarkets);
const mockUseMarket = vi.mocked(useMarket);
const mockUseNetwork = vi.mocked(useNetwork);

const MARKET_COUNT = 100;
const MAX_RENDERED_NODES = 60;

function makeMarketsListData() {
  return {
    markets: Array.from({ length: MARKET_COUNT }, (_, i) => ({
      id: `m${i}`,
      title: `Synthetic market ${i}`,
      status: "active" as const,
      liquidity: 1000,
      volume: 100,
      expires_at: "2026-12-31T00:00:00Z",
    })),
    count: MARKET_COUNT,
    meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" },
  };
}

function makeMarketDetail(marketId: string) {
  return {
    market: {
      id: marketId,
      title: `Synthetic market ${marketId}`,
      description: "",
      variableId: marketId,
      status: "active" as const,
      outcomes: [
        { id: "yes", name: "Yes" },
        { id: "no", name: "No" },
      ],
      marginals: { yes: 0.5, no: 0.5 },
      liquidity: 1000,
      volume: 100,
      created_at: "2026-01-01T00:00:00Z",
      expires_at: "2026-12-31T00:00:00Z",
    },
    meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" },
  };
}

function makeNetworkData() {
  // A star from m0 to every other market: with no other structure, the
  // 2-hop ego graph centered on the (parentless) root m0 pulls in all 100
  // nodes, so the render-cap test actually exercises truncation instead of
  // trivially passing on a 1-node ego set.
  return {
    nodes: [],
    edges: Array.from({ length: MARKET_COUNT - 1 }, (_, i) => ({
      from: "m0",
      to: `m${i + 1}`,
      fromVariableId: "m0",
      toVariableId: `m${i + 1}`,
    })),
    meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" },
  };
}

function queryState<T>(data: T) {
  return {
    data,
    isLoading: false,
    error: null,
    isSuccess: true,
    isError: false,
    isFetching: false,
  } as unknown as ReturnType<typeof useMarket>;
}

describe("BeliefFlowGraph mount storm (>40 nodes)", () => {
  // Track distinct market ids ever passed to useMarket, not raw call count:
  // an effect-driven re-render of the *same* <=60 rendered nodes calls each
  // node's hooks again (normal React behavior, not a regression), so a raw
  // cumulative call count would over-count. What must never happen is
  // useMarket being invoked for markets outside the rendered/capped set --
  // that's the actual "mount storm" (a query fired per market before the
  // prune could apply).
  let calledMarketIds = new Set<string>();

  beforeEach(() => {
    calledMarketIds = new Set();
    mockUseMarkets.mockReturnValue(queryState(makeMarketsListData()) as any);
    mockUseNetwork.mockReturnValue(queryState(makeNetworkData()) as any);
    mockUseMarket.mockImplementation(((marketId: string) => {
      calledMarketIds.add(marketId);
      return queryState(makeMarketDetail(marketId));
    }) as typeof useMarket);
  });

  it("never renders more than MAX_RENDERED_NODES FlowNode groups on first commit for 100 markets", () => {
    const { container } = render(<BeliefFlowGraph />);
    const nodeGroups = container.querySelectorAll("[data-node-id]");
    expect(nodeGroups.length).toBeGreaterThan(0);
    expect(nodeGroups.length).toBeLessThanOrEqual(MAX_RENDERED_NODES);
  });

  it("never invokes useMarket for more markets than the render cap allows", () => {
    render(<BeliefFlowGraph />);
    // Sanity: if the storm regressed, this would be MARKET_COUNT (100).
    expect(calledMarketIds.size).toBeLessThanOrEqual(MAX_RENDERED_NODES);
    expect(calledMarketIds.size).toBeLessThan(MARKET_COUNT);
  });

  it("shows the truncation note when the network exceeds the render cap", () => {
    const { container } = render(<BeliefFlowGraph />);
    expect(container.textContent).toMatch(/Showing 60 of \d+/);
  });
});
