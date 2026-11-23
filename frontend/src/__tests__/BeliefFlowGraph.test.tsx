import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { BeliefFlowGraph } from "@/features/graph/BeliefFlowGraph";
import { AssumptionProvider, useAssumptions } from "@/features/assumptions/AssumptionContext";

vi.mock("@/lib/query/hooks", () => ({
  useMarkets: vi.fn(),
  useMarket: vi.fn(),
  useNetwork: vi.fn(),
  useGraphMarkets: vi.fn(),
}));

import { useMarkets, useMarket, useNetwork, useGraphMarkets } from "@/lib/query/hooks";

const mockUseMarkets = vi.mocked(useMarkets);
const mockUseMarket = vi.mocked(useMarket);
const mockUseNetwork = vi.mocked(useNetwork);
const mockUseGraphMarkets = vi.mocked(useGraphMarkets);

const MARKET_COUNT = 100;
const MAX_RENDERED_NODES = 60;

function makeMarketsListData() {
  return {
    markets: Array.from({ length: MARKET_COUNT }, (_, i) => ({
      id: `m${i}`,
      variableId: `v${i}`,
      title: `Synthetic market ${i}`,
      status: "active" as const,
      liquidity: 1000,
      volume: 100,
      expires_at: "2026-12-31T00:00:00Z",
      marginals: { yes: 0.5, no: 0.5 },
    })),
    count: MARKET_COUNT,
    meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" },
  };
}

function makeStarNetworkData() {
  return {
    nodes: [],
    edges: Array.from({ length: MARKET_COUNT - 1 }, (_, i) => ({
      from: "m0",
      to: `m${i + 1}`,
      fromVariableId: "v0",
      toVariableId: `v${i + 1}`,
    })),
    meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" },
  };
}

function makeChainNetworkData() {
  return {
    nodes: [],
    edges: Array.from({ length: MARKET_COUNT - 1 }, (_, i) => ({
      from: `m${i}`,
      to: `m${i + 1}`,
      fromVariableId: `v${i}`,
      toVariableId: `v${i + 1}`,
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

function AssumptionSeeder() {
  const { addAssumption } = useAssumptions();
  return (
    <button
      type="button"
      data-testid="seed-assumption"
      onClick={() => addAssumption({ variableId: "v50", outcomeId: "yes", label: "Synthetic market 50" })}
    >
      Seed
    </button>
  );
}

describe("BeliefFlowGraph", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMarkets.mockReturnValue(queryState(makeMarketsListData()) as any);
    mockUseNetwork.mockReturnValue(queryState(makeStarNetworkData()) as any);
    mockUseGraphMarkets.mockReturnValue(queryState(undefined) as any);
    mockUseMarket.mockReturnValue(queryState(undefined) as any);
  });

  it("never renders more than MAX_RENDERED_NODES FlowNode groups on first commit for 100 markets", () => {
    const { container } = renderWithProviders(<BeliefFlowGraph />);
    const nodeGroups = container.querySelectorAll("[data-node-id]");
    expect(nodeGroups.length).toBeGreaterThan(0);
    expect(nodeGroups.length).toBeLessThanOrEqual(MAX_RENDERED_NODES);
  });

  it("never invokes per-node useMarket on render or when assumptions are active (no DeltaProbe storm)", () => {
    mockUseNetwork.mockReturnValue(queryState(makeChainNetworkData()) as any);
    mockUseGraphMarkets.mockReturnValue(
      queryState({
        markets: [
          { id: "m50", variableId: "v50", title: "Synthetic market 50", status: "active", marginals: { yes: 0.5, no: 0.5 }, conditionalMarginals: { yes: 1, no: 0 } },
          { id: "m51", variableId: "v51", title: "Synthetic market 51", status: "active", marginals: { yes: 0.5, no: 0.5 }, conditionalMarginals: { yes: 0.85, no: 0.15 } },
        ],
        meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" },
      }) as any,
    );

    renderWithProviders(
      <AssumptionProvider>
        <AssumptionSeeder />
        <BeliefFlowGraph focusMarketId="m50" />
      </AssumptionProvider>,
    );

    expect(mockUseMarket).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("seed-assumption"));
    // Even with active assumptions across 100 markets, zero per-node useMarket calls fire!
    expect(mockUseMarket).not.toHaveBeenCalled();
    expect(screen.getByText("Top movers")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Synthetic market 51/ })).toBeInTheDocument();
  });

  it("shows the truncation note when the network exceeds the render cap", () => {
    const { container } = renderWithProviders(<BeliefFlowGraph />);
    expect(container.textContent).toMatch(/Showing 60 of \d+/);
  });

  it("immediately focuses on focusMarketId (never stuck on m0) and supports 1-hop / 2-hop / Reset scope controls", () => {
    mockUseNetwork.mockReturnValue(queryState(makeChainNetworkData()) as any);

    const { container } = renderWithProviders(<BeliefFlowGraph focusMarketId="m50" />);

    // Default 2-hop around m50 in chain: m48, m49, m50, m51, m52 (5 nodes) — NOT m0!
    const twoHopIds = Array.from(container.querySelectorAll("[data-node-id]")).map((el) =>
      el.getAttribute("data-node-id"),
    );
    expect(twoHopIds.sort()).toEqual(["m48", "m49", "m50", "m51", "m52"]);
    expect(twoHopIds).not.toContain("m0");

    // Clicking 1-hop contracts to direct parents & children: m49, m50, m51
    fireEvent.click(screen.getByRole("button", { name: "1-hop" }));
    const oneHopIds = Array.from(container.querySelectorAll("[data-node-id]")).map((el) =>
      el.getAttribute("data-node-id"),
    );
    expect(oneHopIds.sort()).toEqual(["m49", "m50", "m51"]);

    // Clicking Reset to this market restores 2-hop around m50
    fireEvent.click(screen.getByRole("button", { name: "Reset to this market" }));
    const resetIds = Array.from(container.querySelectorAll("[data-node-id]")).map((el) =>
      el.getAttribute("data-node-id"),
    );
    expect(resetIds.sort()).toEqual(["m48", "m49", "m50", "m51", "m52"]);
  });

  it("searches across ALL markets in Find event dropdown and refocuses on any off-screen match", () => {
    mockUseNetwork.mockReturnValue(queryState(makeChainNetworkData()) as any);

    const { container } = renderWithProviders(<BeliefFlowGraph focusMarketId="m50" />);

    const input = screen.getByLabelText("Find event");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "market 85" } });

    const option = screen.getByRole("option", { name: /Synthetic market 85/ });
    fireEvent.mouseDown(option);

    const newIds = Array.from(container.querySelectorAll("[data-node-id]")).map((el) =>
      el.getAttribute("data-node-id"),
    );
    expect(newIds).toContain("m85");
    expect(newIds).not.toContain("m50");
  });

  it("renders the double-click hint and disables text selection on SVG labels", () => {
    mockUseNetwork.mockReturnValue(queryState(makeChainNetworkData()) as any);
    const { container } = renderWithProviders(<BeliefFlowGraph focusMarketId="m50" />);
    expect(screen.getByText(/Click to inspect · Double-click to refocus/)).toBeInTheDocument();
    const svg = container.querySelector("svg")!;
    expect(svg.style.userSelect).toBe("none");
  });
});
