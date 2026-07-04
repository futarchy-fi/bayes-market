import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { NetworkMap } from "@/features/graph/NetworkMap";
import { AssumptionProvider, useAssumptions } from "@/features/assumptions/AssumptionContext";
import type { GraphMarket } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mocks: the map reads everything from one bulk useGraphMarkets response, so
// that's the only query hook it needs mocked. useMarkets/useMarket are not
// used by NetworkMap at all (no per-node queries).
// ---------------------------------------------------------------------------

vi.mock("@/lib/query/hooks", () => ({
  useGraphMarkets: vi.fn(),
}));

import { useGraphMarkets } from "@/lib/query/hooks";

const mockUseGraphMarkets = vi.mocked(useGraphMarkets);

// ---------------------------------------------------------------------------
// Fixtures: 20 markets spanning several families, a couple of external
// imports sharing a year (to exercise collision nudging), and a parent/child
// chain so hover/edge highlighting has something to show.
// ---------------------------------------------------------------------------

function market(overrides: Partial<GraphMarket> & Pick<GraphMarket, "id" | "title">): GraphMarket {
  return {
    status: "active",
    marginals: { yes: 0.5, no: 0.5 },
    ...overrides,
  };
}

function makeGraphMarkets(): GraphMarket[] {
  return [
    market({ id: "m1", variableId: "ftm_agi_by_2030", title: "AGI compute threshold by 2030", marginals: { yes: 0.3, no: 0.7 } }),
    market({
      id: "m2",
      variableId: "ftm_rampup_by_2031",
      title: "Economic ramp-up by 2031",
      parents: ["ftm_agi_by_2030"],
      marginals: { yes: 0.25, no: 0.75 },
    }),
    market({
      id: "m3",
      variableId: "ftm_auto_goods_t0_by_2032",
      title: "Task automation 5% by 2032",
      parents: ["ftm_rampup_by_2031"],
      marginals: { yes: 0.4, no: 0.6 },
    }),
    market({ id: "m4", variableId: "ftm_auto_goods_t3_by_2038", title: "Task automation 90% by 2038", marginals: { yes: 0.1, no: 0.9 } }),
    market({ id: "m5", variableId: "ftm_full_auto_by_2040", title: "Full automation by 2040", marginals: { yes: 0.05, no: 0.95 } }),
    market({ id: "m6", variableId: "ftm_rampup_rnd_by_2031", title: "R&D ramp-up by 2031", marginals: { yes: 0.2, no: 0.8 } }),
    market({ id: "m7", variableId: "ftm_auto_rnd_t1_by_2033", title: "R&D task automation 20% by 2033", marginals: { yes: 0.35, no: 0.65 } }),
    market({ id: "m8", variableId: "ftm_full_auto_rnd_by_2041", title: "Full R&D automation by 2041", marginals: { yes: 0.06, no: 0.94 } }),
    market({ id: "m9", variableId: "ftm_train_run_t2_by_2029", title: "Largest training run 1e31 by 2029", marginals: { yes: 0.5, no: 0.5 } }),
    market({ id: "m10", variableId: "ftm_gwp_compute_t1_in_2032", title: "Compute investment share by 2032", marginals: { yes: 0.3, no: 0.7 } }),
    market({ id: "m11", variableId: "ftm_hw_ratio_t0_by_2028", title: "Hardware price-performance by 2028", marginals: { yes: 0.6, no: 0.4 } }),
    market({ id: "m12", variableId: "ftm_sw_ratio_t2_by_2036", title: "Software efficiency by 2036", marginals: { yes: 0.45, no: 0.55 } }),
    market({ id: "m13", variableId: "ftm_gwp_growth_t1_in_2031", title: "GWP growth 20% in 2031", marginals: { yes: 0.5, no: 0.5 } }),
    market({ id: "m14", variableId: "ftm_gwp_growth_max_t1_in_2031", title: "GWP growth ever exceeds 20% by 2031", marginals: { yes: 0.55, no: 0.45 } }),
    market({
      id: "x1",
      variableId: "x_0001",
      title: "Metaculus: AGI by 2030?",
      anchor: { source: "metaculus", ref: "q1", url: "https://metaculus.com/q1", value: 0.4, fetchedAt: "" },
      marginals: { yes: 0.42, no: 0.58 },
    }),
    market({
      id: "x2",
      variableId: "x_0002",
      title: "Manifold: transformative AI by 2030?",
      anchor: { source: "manifold", ref: "q2", url: "https://manifold.markets/q2", value: 0.38, fetchedAt: "" },
      marginals: { yes: 0.38, no: 0.62 },
    }),
    market({ id: "x3", variableId: "x_0003", title: "Metaculus: superintelligence by 2030?", marginals: { yes: 0.2, no: 0.8 } }),
    market({ id: "orig1", variableId: "misc_variable_a", title: "A hand-authored original", marginals: { yes: 0.5, no: 0.5 }, ftmImplied: 0.48 }),
    market({ id: "orig2", variableId: "misc_variable_b", title: "Another hand-authored original", marginals: { yes: 0.33, no: 0.67 } }),
    market({ id: "orig3", variableId: "misc_variable_c", title: "Yet another original market", marginals: { yes: 0.7, no: 0.3 } }),
  ];
}

function queryState(markets: GraphMarket[]) {
  return {
    data: { markets, meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" } },
    isLoading: false,
    error: null,
    isSuccess: true,
    isError: false,
    isFetching: false,
  } as unknown as ReturnType<typeof useGraphMarkets>;
}

function Seeder({ variableId, outcomeId, label }: { variableId: string; outcomeId: string; label: string }) {
  const { addAssumption } = useAssumptions();
  return (
    <button data-testid="seed" onClick={() => addAssumption({ variableId, outcomeId, label })} style={{ display: "none" }} />
  );
}

function renderMap(markets: GraphMarket[] = makeGraphMarkets()) {
  mockUseGraphMarkets.mockReturnValue(queryState(markets));
  return renderWithProviders(
    <AssumptionProvider>
      <NetworkMap />
    </AssumptionProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("NetworkMap", () => {
  it("renders a node per market and the market/link count in the toolbar", () => {
    const markets = makeGraphMarkets();
    const { container } = renderMap(markets);
    const nodeCircles = container.querySelectorAll("circle[data-node-id]");
    // Two circles per node: fill + transparent hit-target overlay.
    const uniqueIds = new Set(Array.from(nodeCircles).map((c) => c.getAttribute("data-node-id")));
    expect(uniqueIds.size).toBe(markets.length);
    expect(screen.getByText(`${markets.length} markets · 2 links`)).toBeInTheDocument();
  });

  it("renders a bezier path per CPT edge", () => {
    const { container } = renderMap();
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBe(2); // m1->m2, m2->m3
  });

  it("highlights incident edges and neighbor nodes on hover, dimming the rest", () => {
    const { container } = renderMap();
    const hitNode = container.querySelectorAll('circle[data-node-id="m1"]')[1] as SVGCircleElement;
    fireEvent.mouseOver(hitNode);

    const m1Fill = container.querySelector('circle[data-node-id="m1"]') as SVGCircleElement;
    const m2Fill = container.querySelector('circle[data-node-id="m2"]') as SVGCircleElement; // child of m1
    const m9Fill = container.querySelector('circle[data-node-id="m9"]') as SVGCircleElement; // unrelated

    expect(m1Fill.getAttribute("opacity")).toBe("1");
    expect(m2Fill.getAttribute("opacity")).toBe("1");
    expect(m9Fill.getAttribute("opacity")).toBe("0.15");
  });

  it("opens a popover with market details when a node is clicked", () => {
    const { container } = renderMap();
    const hitNode = container.querySelectorAll('circle[data-node-id="m1"]')[1] as SVGCircleElement;
    fireEvent.click(hitNode);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("AGI compute threshold by 2030")).toBeInTheDocument();
    expect(screen.getByText("30.0%")).toBeInTheDocument();
    expect(screen.getByText("Open market →")).toBeInTheDocument();
  });

  it("closes the popover when clicking elsewhere on the map", () => {
    const { container } = renderMap();
    const hitNode = container.querySelectorAll('circle[data-node-id="m1"]')[1] as SVGCircleElement;
    fireEvent.click(hitNode);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    const svg = container.querySelector("svg")!;
    fireEvent.click(svg);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("wires 'Assume YES' in the popover to the AssumptionContext", () => {
    const { container } = renderMap();
    const hitNode = container.querySelectorAll('circle[data-node-id="m1"]')[1] as SVGCircleElement;
    fireEvent.click(hitNode);

    fireEvent.click(screen.getByText("Assume YES"));
    // Once assumed, the popover should offer to clear it instead of assuming again.
    expect(screen.getByText("Clear assumption")).toBeInTheDocument();
  });

  it("dims non-matching nodes when searching", () => {
    const { container } = renderMap();
    fireEvent.change(screen.getByLabelText("Search markets"), { target: { value: "AGI compute" } });

    const m1Fill = container.querySelector('circle[data-node-id="m1"]') as SVGCircleElement;
    const m9Fill = container.querySelector('circle[data-node-id="m9"]') as SVGCircleElement;
    expect(m1Fill.getAttribute("opacity")).toBe("1");
    expect(m9Fill.getAttribute("opacity")).toBe("0.15");
  });

  it("requests the graph with a context param once an assumption is active", () => {
    renderMap();
    expect(mockUseGraphMarkets).toHaveBeenLastCalledWith([]);

    renderWithProviders(
      <AssumptionProvider>
        <Seeder variableId="ftm_agi_by_2030" outcomeId="yes" label="AGI" />
        <NetworkMap />
      </AssumptionProvider>,
    );
    fireEvent.click(screen.getByTestId("seed"));

    expect(mockUseGraphMarkets).toHaveBeenLastCalledWith([{ variableId: "ftm_agi_by_2030", outcomeId: "yes" }]);
  });

  it("shows the legend and delta-colored nodes only once an assumption is active", () => {
    const markets = makeGraphMarkets().map((m) =>
      m.id === "m2" ? { ...m, conditionalMarginals: { yes: 0.6, no: 0.4 } } : m,
    );
    mockUseGraphMarkets.mockReturnValue(queryState(markets));

    function Wrapper() {
      return (
        <AssumptionProvider>
          <Seeder variableId="ftm_agi_by_2030" outcomeId="yes" label="AGI" />
          <NetworkMap />
        </AssumptionProvider>
      );
    }
    renderWithProviders(<Wrapper />);

    expect(screen.queryByText("No meaningful change")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("seed"));
    expect(screen.getByText("No meaningful change")).toBeInTheDocument();
  });
});
