import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { AssumptionPanel } from "@/features/assumptions/AssumptionPanel";
import { AssumptionProvider, useAssumptions } from "@/features/assumptions/AssumptionContext";
import type { Market } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/features/assumptions/VariableRow", () => ({
  VariableRow: vi.fn(({ marketId, targetMarket }: { marketId: string; targetMarket: Market }) => (
    <div data-testid={`variable-row-${marketId}`}>
      VariableRow: {marketId} (target: {targetMarket.id})
    </div>
  )),
}));

vi.mock("@/lib/query/hooks", () => ({
  useNetwork: vi.fn(() => ({ data: undefined })),
  useMarkets: vi.fn(),
}));

import { useMarkets } from "@/lib/query/hooks";
import { VariableRow } from "@/features/assumptions/VariableRow";

const mockUseMarkets = vi.mocked(useMarkets);
const mockVariableRow = vi.mocked(VariableRow);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const currentMarket: Market = {
  id: "mkt-current",
  title: "Will it rain?",
  description: "Rain forecast",
  variableId: "var-rain",
  status: "active",
  outcomes: [
    { id: "out-yes", name: "Yes" },
    { id: "out-no", name: "No" },
  ],
  marginals: { "out-yes": 0.6, "out-no": 0.4 },
  liquidity: 1000,
  volume: 500,
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-12-31T00:00:00Z",
};

function makeMarket(id: string, title: string): Market {
  return {
    id,
    title,
    description: `${title} description`,
    variableId: `var-${id}`,
    status: "active",
    outcomes: [
      { id: `${id}-yes`, name: "Yes" },
      { id: `${id}-no`, name: "No" },
    ],
    marginals: { [`${id}-yes`]: 0.5, [`${id}-no`]: 0.5 },
    liquidity: 100,
    volume: 50,
    created_at: "2026-01-01T00:00:00Z",
    expires_at: "2026-12-31T00:00:00Z",
  };
}

const marketB = makeMarket("mkt-b", "Market B");
const marketC = makeMarket("mkt-c", "Market C");

function threeActiveMarkets() {
  return {
    data: {
      markets: [currentMarket, marketB, marketC],
    },
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useMarkets>;
}

function singleActiveMarket() {
  return {
    data: { markets: [currentMarket] },
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useMarkets>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Render AssumptionPanel wrapped in a local AssumptionProvider.
 * Optionally pre-populate assumptions via an `init` callback that fires
 * before the component under test mounts — we achieve this by rendering a
 * small bootstrapper that calls addAssumption inside an effect-free click.
 */
function renderPanel(
  { market = currentMarket, initialAssumptions = [] as Array<{ variableId: string; outcomeId: string; label: string }> } = {},
) {
  // We wrap in AssumptionProvider locally (decision d5).
  // To pre-seed assumptions, we render a helper button that adds them.
  function Wrapper() {
    return (
      <AssumptionProvider>
        <Seeder assumptions={initialAssumptions} />
        <AssumptionPanel market={market} />
      </AssumptionProvider>
    );
  }

  return renderWithProviders(<Wrapper />);
}

/**
 * Invisible component that seeds assumptions into context when its
 * "seed-assumptions" button is clicked.
 */
function Seeder({ assumptions }: { assumptions: Array<{ variableId: string; outcomeId: string; label: string }> }) {
  const { addAssumption } = useAssumptions();
  return (
    <button
      data-testid="seed-assumptions"
      onClick={() => assumptions.forEach((a) => addAssumption(a))}
      style={{ display: "none" }}
    />
  );
}

function seedAssumptions() {
  fireEvent.click(screen.getByTestId("seed-assumptions"));
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockUseMarkets.mockReturnValue(threeActiveMarkets());
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AssumptionPanel", () => {
  it("renders heading and marginal probabilities status when no assumptions", () => {
    renderPanel();

    expect(screen.getByText("Variables & Assumptions")).toBeInTheDocument();
    expect(screen.getByText("Showing marginal probabilities")).toBeInTheDocument();
  });

  it("renders correct status text when assumptions are set", () => {
    renderPanel({
      initialAssumptions: [
        { variableId: "var-mkt-b", outcomeId: "mkt-b-yes", label: "Market B" },
      ],
    });
    seedAssumptions();

    expect(screen.getByText(/Showing conditionals given 1 assumption$/)).toBeInTheDocument();

    // Add a second assumption — use a fresh render to check pluralisation
  });

  it("renders correct pluralised status for multiple assumptions", () => {
    renderPanel({
      initialAssumptions: [
        { variableId: "var-mkt-b", outcomeId: "mkt-b-yes", label: "Market B" },
        { variableId: "var-mkt-c", outcomeId: "mkt-c-yes", label: "Market C" },
      ],
    });
    seedAssumptions();

    expect(screen.getByText(/Showing conditionals given 2 assumptions$/)).toBeInTheDocument();
  });

  it("renders VariableRow for each active market with current market first", () => {
    renderPanel();

    // 3 VariableRow renders (one per active market)
    expect(mockVariableRow).toHaveBeenCalledTimes(3);

    // First call should be the current market
    expect(mockVariableRow.mock.calls[0]![0]).toMatchObject({
      marketId: "mkt-current",
    });

    // Verify all three are in the document
    expect(screen.getByTestId("variable-row-mkt-current")).toBeInTheDocument();
    expect(screen.getByTestId("variable-row-mkt-b")).toBeInTheDocument();
    expect(screen.getByTestId("variable-row-mkt-c")).toBeInTheDocument();
  });

  it("shows create-more-markets message when only one active market", () => {
    mockUseMarkets.mockReturnValue(singleActiveMarket());
    renderPanel();

    expect(screen.getByText(/Create more markets to use assumptions/)).toBeInTheDocument();
  });

  it("hides create-more-markets message when multiple active markets", () => {
    mockUseMarkets.mockReturnValue(threeActiveMarkets());
    renderPanel();

    expect(screen.queryByText(/Create more markets to use assumptions/)).not.toBeInTheDocument();
  });

  it("AssumptionBar shows assumption tags with GIVEN label", () => {
    renderPanel({
      initialAssumptions: [
        { variableId: "var-mkt-b", outcomeId: "mkt-b-yes", label: "Market B" },
      ],
    });
    seedAssumptions();

    expect(screen.getByText("GIVEN:")).toBeInTheDocument();
    expect(screen.getByText(/Market B/)).toBeInTheDocument();
  });

  it("AssumptionBar hidden when no assumptions", () => {
    renderPanel();

    expect(screen.queryByText("GIVEN:")).not.toBeInTheDocument();
  });

  it("clear all button removes all assumptions", () => {
    renderPanel({
      initialAssumptions: [
        { variableId: "var-mkt-b", outcomeId: "mkt-b-yes", label: "Market B" },
        { variableId: "var-mkt-c", outcomeId: "mkt-c-yes", label: "Market C" },
      ],
    });
    seedAssumptions();

    // Verify assumptions are present
    expect(screen.getByText("GIVEN:")).toBeInTheDocument();
    expect(screen.getByText(/Showing conditionals given 2 assumptions/)).toBeInTheDocument();

    // Click "Clear all"
    fireEvent.click(screen.getByText("Clear all"));

    // After clearing, should revert to marginal
    expect(screen.getByText("Showing marginal probabilities")).toBeInTheDocument();
    expect(screen.queryByText("GIVEN:")).not.toBeInTheDocument();
  });

  it("remove individual assumption via tag close button", () => {
    renderPanel({
      initialAssumptions: [
        { variableId: "var-mkt-b", outcomeId: "mkt-b-yes", label: "Market B" },
        { variableId: "var-mkt-c", outcomeId: "mkt-c-yes", label: "Market C" },
      ],
    });
    seedAssumptions();

    // Both should be present
    expect(screen.getByText(/Market B/)).toBeInTheDocument();
    expect(screen.getByText(/Market C/)).toBeInTheDocument();

    // Click remove on Market B's tag
    fireEvent.click(screen.getByLabelText("Remove assumption Market B"));

    // Market B should be gone, Market C should remain
    expect(screen.queryByText(/Market B = mkt-b-yes/)).not.toBeInTheDocument();
    expect(screen.getByText(/Market C/)).toBeInTheDocument();
    expect(screen.getByText(/Showing conditionals given 1 assumption$/)).toBeInTheDocument();
  });
});
