import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { ConditionalEditor } from "@/features/trading/ConditionalEditor";
import type { Market, MarketSummary } from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockMutate = vi.fn();

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
  useProbabilityEdit: vi.fn(),
  useMarkets: vi.fn(),
  useMarket: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import { useProbabilityEdit, useMarkets, useMarket } from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseProbabilityEdit = vi.mocked(useProbabilityEdit);
const mockUseMarkets = vi.mocked(useMarkets);
const mockUseMarket = vi.mocked(useMarket);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockMarket: Market = {
  id: "mkt-cond-1",
  title: "Will BTC hit 100k?",
  description: "Bitcoin price market",
  variableId: "var-btc",
  status: "active",
  outcomes: [
    { id: "out-yes", name: "Yes" },
    { id: "out-no", name: "No" },
  ],
  marginals: { "out-yes": 0.72, "out-no": 0.28 },
  liquidity: 5000,
  volume: 2000,
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-12-31T00:00:00Z",
};

const configuredSession = {
  session: { accountId: "acc-456", agentId: "agent-2" },
  setAccountId: vi.fn(),
  setAgentId: vi.fn(),
  isConfigured: true,
};

const unconfiguredSession = {
  session: { accountId: "", agentId: "" },
  setAccountId: vi.fn(),
  setAgentId: vi.fn(),
  isConfigured: false,
};

const mockOtherMarkets: MarketSummary[] = [
  { id: "mkt-other-1", title: "Election Winner", status: "active", liquidity: 3000, volume: 1500, expires_at: "2026-11-01T00:00:00Z" },
  { id: "mkt-other-2", title: "Inactive Market", status: "closed", liquidity: 100, volume: 50, expires_at: "2025-06-01T00:00:00Z" },
  { id: "mkt-cond-1", title: "Same as current", status: "active", liquidity: 5000, volume: 2000, expires_at: "2026-12-31T00:00:00Z" },
];

const mockContextMarketOutcomes = {
  market: {
    id: "mkt-other-1",
    title: "Election Winner",
    description: "Election market",
    variableId: "var-elect",
    status: "active" as const,
    outcomes: [
      { id: "out-dem", name: "Democrat" },
      { id: "out-rep", name: "Republican" },
    ],
    marginals: { "out-dem": 0.55, "out-rep": 0.45 },
    liquidity: 3000,
    volume: 1500,
    created_at: "2026-01-01T00:00:00Z",
    expires_at: "2026-11-01T00:00:00Z",
  },
  meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" },
};

function defaultMutationState(overrides: Record<string, unknown> = {}) {
  return {
    mutate: mockMutate,
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
    ...overrides,
  } as unknown as ReturnType<typeof useProbabilityEdit>;
}

function defaultQueryState(overrides: Record<string, unknown> = {}) {
  return {
    data: undefined,
    error: null,
    isError: false,
    isLoading: false,
    isPending: false,
    isSuccess: true,
    status: "success" as const,
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    errorUpdateCount: 0,
    fetchStatus: "idle" as const,
    isLoadingError: false,
    isFetched: true,
    isFetchedAfterMount: true,
    isFetching: false,
    isInitialLoading: false,
    isPlaceholderData: false,
    isRefetchError: false,
    isRefetching: false,
    isStale: false,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as ReturnType<typeof useMarkets>;
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSession.mockReturnValue(configuredSession);
  mockUseProbabilityEdit.mockReturnValue(defaultMutationState());
  mockUseMarkets.mockReturnValue(
    defaultQueryState({
      data: { markets: mockOtherMarkets, count: mockOtherMarkets.length, meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" } },
    }) as unknown as ReturnType<typeof useMarkets>,
  );
  mockUseMarket.mockReturnValue(
    defaultQueryState({
      data: mockContextMarketOutcomes,
    }) as unknown as ReturnType<typeof useMarket>,
  );
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ConditionalEditor", () => {
  it("shows setup message when session is not configured", () => {
    mockUseSession.mockReturnValue(unconfiguredSession);
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("renders form with outcome select, probability slider, and submit button", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    expect(screen.getByRole("heading", { name: "Conditional Probability Edit" })).toBeInTheDocument();

    // Outcome select with current probabilities
    const selects = screen.getAllByRole("combobox");
    expect(selects.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Yes (current: 72.0%)")).toBeInTheDocument();
    expect(screen.getByText("No (current: 28.0%)")).toBeInTheDocument();

    // Slider
    expect(screen.getByRole("slider")).toBeInTheDocument();

    // Submit button (unconditional when no context)
    expect(screen.getByRole("button", { name: "Submit Unconditional Edit" })).toBeInTheDocument();
  });

  it("shows unconditional notation without context", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    expect(screen.getByText("Set P(Yes) = 50.0%")).toBeInTheDocument();
  });

  it("Add condition button adds a context row", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    const addButton = screen.getByRole("button", { name: /Add condition/ });
    fireEvent.click(addButton);

    // A context row should appear with market select placeholder
    expect(screen.getByText("Select market...")).toBeInTheDocument();
    expect(screen.getByText("Select outcome...")).toBeInTheDocument();
  });

  it("Add condition button is disabled when no other markets available", () => {
    mockUseMarkets.mockReturnValue(
      defaultQueryState({
        data: {
          markets: [
            // Only our own market and inactive ones — no valid other active markets
            { id: "mkt-cond-1", title: "Same as current", status: "active", liquidity: 5000, volume: 2000, expires_at: "2026-12-31T00:00:00Z" },
            { id: "mkt-other-2", title: "Inactive Market", status: "closed", liquidity: 100, volume: 50, expires_at: "2025-06-01T00:00:00Z" },
          ],
          count: 2,
          meta: { apiVersion: "1.0", timestamp: "2026-01-01T00:00:00Z" },
        },
      }) as unknown as ReturnType<typeof useMarkets>,
    );
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    const addButton = screen.getByRole("button", { name: /Add condition/ });
    expect(addButton).toBeDisabled();
  });

  it("context row market select shows only other active markets", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    const addButton = screen.getByRole("button", { name: /Add condition/ });
    fireEvent.click(addButton);

    // Should show "Election Winner" (active, different id) but not "Inactive Market" (closed) or "Same as current" (same id)
    expect(screen.getByText("Election Winner")).toBeInTheDocument();
    expect(screen.queryByText("Inactive Market")).not.toBeInTheDocument();
    // "Same as current" has the same id as mockMarket so it's filtered out
    expect(screen.queryByText("Same as current")).not.toBeInTheDocument();
  });

  it("selecting a market in context row populates outcome dropdown", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    // Add a context row
    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));

    // Find the market select in the context row (second combobox after the outcome selector)
    const selects = screen.getAllByRole("combobox");
    // First combobox is the target outcome, second is the context market, third is context outcome
    const marketSelect = selects[1]!;
    fireEvent.change(marketSelect, { target: { value: "mkt-other-1" } });

    // useMarket should have been called with the selected market id
    expect(mockUseMarket).toHaveBeenCalledWith("mkt-other-1", { enabled: true });

    // Outcomes from the mocked useMarket response should appear
    expect(screen.getByText("Democrat")).toBeInTheDocument();
    expect(screen.getByText("Republican")).toBeInTheDocument();
  });

  it("remove button removes a context row", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    // Add a context row
    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));
    expect(screen.getByText("Select market...")).toBeInTheDocument();

    // Click the remove button (×)
    const removeButton = screen.getByRole("button", { name: "×" });
    fireEvent.click(removeButton);

    // Context row should be gone — the "Select market..." placeholder should no longer be present
    // But the unconditional message should reappear
    expect(screen.getByText(/No conditions/)).toBeInTheDocument();
  });

  it("notation updates when conditions are added", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    // Add a context row
    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));

    // Select market and outcome
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[1]!, { target: { value: "mkt-other-1" } });
    fireEvent.change(selects[2]!, { target: { value: "out-dem" } });

    // Notation should now show conditional format
    expect(screen.getByText(/Set P\(Yes \| mkt-other-1=out-dem\) = 50\.0%/)).toBeInTheDocument();
  });

  it("submits correct payload with context conditions", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    // Change outcome to No
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[0]!, { target: { value: "out-no" } });

    // Change probability
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0.4" } });

    // Add context and fill it in
    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));
    const allSelects = screen.getAllByRole("combobox");
    fireEvent.change(allSelects[1]!, { target: { value: "mkt-other-1" } });
    fireEvent.change(allSelects[2]!, { target: { value: "out-dem" } });

    // Submit
    fireEvent.click(screen.getByRole("button", { name: "Submit Conditional Edit" }));

    expect(mockMutate).toHaveBeenCalledTimes(1);
    const call = mockMutate.mock.calls[0]![0];
    expect(call.payload.accountId).toBe("acc-456");
    expect(call.payload.variableId).toBe("var-btc");
    expect(call.payload.target).toEqual({
      kind: "marginal",
      outcomeId: "out-no",
      probability: 0.4,
    });
    expect(call.payload.context).toEqual([
      { variableId: "mkt-other-1", outcomeId: "out-dem" },
    ]);
    expect(call.payload.idempotencyKey).toBeDefined();
    expect(call.session).toEqual({ accountId: "acc-456", agentId: "agent-2" });
  });

  it("submit button shows conditional text and pending state", () => {
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    // Add a context row so we get "Submit Conditional Edit"
    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));
    expect(screen.getByRole("button", { name: "Submit Conditional Edit" })).toBeInTheDocument();

    // Now test pending state
    mockUseProbabilityEdit.mockReturnValue(
      defaultMutationState({ isPending: true, isIdle: false, status: "pending" }),
    );
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    const button = screen.getByRole("button", { name: /Submitting/ });
    expect(button).toBeDisabled();
  });

  it("shows success message with conditional prefix", () => {
    mockUseProbabilityEdit.mockReturnValue(
      defaultMutationState({
        isSuccess: true,
        isIdle: false,
        status: "success",
        data: { order: { orderId: "order-cond-789" } },
      }),
    );
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    // No context rows — should show "Edit accepted"
    expect(screen.getByText(/Edit accepted: order-cond-789/)).toBeInTheDocument();
  });

  it("shows error message when mutation fails", () => {
    mockUseProbabilityEdit.mockReturnValue(
      defaultMutationState({
        isError: true,
        isIdle: false,
        status: "error",
        error: new Error("Probability out of range"),
      }),
    );
    renderWithProviders(<ConditionalEditor market={mockMarket} />);

    expect(screen.getByText("Probability out of range")).toBeInTheDocument();
  });
});
