import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { EventTradePanel } from "@/features/trading/EventTradePanel";
import type { Market } from "@/lib/api/types";

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
  useEventTrade: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import { useEventTrade } from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseEventTrade = vi.mocked(useEventTrade);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockMarket: Market = {
  id: "mkt-1",
  title: "Will it rain tomorrow?",
  description: "Rain forecast market",
  variableId: "var-1",
  status: "active",
  outcomes: [
    { id: "out-yes", name: "Yes" },
    { id: "out-no", name: "No" },
  ],
  marginals: { "out-yes": 0.65, "out-no": 0.35 },
  liquidity: 1000,
  volume: 500,
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-12-31T00:00:00Z",
};

const configuredSession = {
  session: { accountId: "acc-123", agentId: "agent-1" },
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
  } as unknown as ReturnType<typeof useEventTrade>;
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSession.mockReturnValue(configuredSession);
  mockUseEventTrade.mockReturnValue(defaultMutationState());
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EventTradePanel", () => {
  // Step 2: Guard clause tests
  it("renders nothing when market status is not active", () => {
    const closedMarket = { ...mockMarket, status: "closed" as Market["status"] };
    const { container } = renderWithProviders(<EventTradePanel market={closedMarket} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when session is unconfigured", () => {
    mockUseSession.mockReturnValue(unconfiguredSession);
    const { container } = renderWithProviders(<EventTradePanel market={mockMarket} />);
    expect(container.firstChild).toBeNull();
  });

  // Step 3: Rendering test
  it("renders Quick Trade heading, Buy/Sell toggles, outcome selector, and trade button", () => {
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    expect(screen.getByText("Quick Trade")).toBeInTheDocument();

    // Buy/Sell toggle buttons
    expect(screen.getByRole("button", { name: "Buy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sell" })).toBeInTheDocument();

    // Outcome selector with marginal probabilities
    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    expect(screen.getByText("Yes @ 65.0%")).toBeInTheDocument();
    expect(screen.getByText("No @ 35.0%")).toBeInTheDocument();

    // Trade button (defaults to buy, no outcome selected yet)
    expect(screen.getByRole("button", { name: "Buy ..." })).toBeInTheDocument();
  });

  // Step 4: Interaction tests
  it("toggles to sell side when Sell button is clicked", () => {
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    const sellBtn = screen.getByRole("button", { name: "Sell" });
    fireEvent.click(sellBtn);

    // Submit button text updates to reflect sell side
    expect(screen.getByRole("button", { name: "Sell ..." })).toBeInTheDocument();
  });

  it("shows Price label with correct percentage when outcome is selected", () => {
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "out-yes" } });

    expect(screen.getByText("Price: 65.0%")).toBeInTheDocument();
  });

  // Step 5: Submission test with buy side
  it("calls mutation.mutate with correct payload on buy submission", () => {
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    // Select outcome
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "out-yes" } });

    // Click trade button
    const button = screen.getByRole("button", { name: "Buy out-yes" });
    fireEvent.click(button);

    expect(mockMutate).toHaveBeenCalledTimes(1);
    const call = mockMutate.mock.calls[0]![0];
    expect(call.payload.accountId).toBe("acc-123");
    expect(call.payload.formula).toEqual([[{ variableId: "mkt-1", outcomeId: "out-yes", negated: false }]]);
    expect(call.payload.side).toBe("buy");
    expect(call.payload.idempotencyKey).toBeDefined();
    expect(call.session).toEqual({ accountId: "acc-123", agentId: "agent-1" });
  });

  // Step 6: Submission with sell side
  it("submits with sell side when toggled to sell", () => {
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    // Toggle to sell
    fireEvent.click(screen.getByRole("button", { name: "Sell" }));

    // Select outcome
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "out-no" } });

    // Submit
    fireEvent.click(screen.getByRole("button", { name: "Sell out-no" }));

    expect(mockMutate).toHaveBeenCalledTimes(1);
    expect(mockMutate.mock.calls[0]![0].payload.side).toBe("sell");
  });

  // Step 7: Pending state
  it("shows Submitting text and disables button when mutation is pending", () => {
    mockUseEventTrade.mockReturnValue(
      defaultMutationState({ isPending: true, isIdle: false, status: "pending" }),
    );
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    const button = screen.getByRole("button", { name: /Submitting/ });
    expect(button).toBeDisabled();
  });

  // Step 8: Success state with TradeReceipt
  it("shows success message with orderId and TradeReceipt values", () => {
    mockUseEventTrade.mockReturnValue(
      defaultMutationState({
        isSuccess: true,
        isIdle: false,
        status: "success",
        data: {
          order: { orderId: "order-evt-456" },
          assetDelta: {
            beforeMinAsset: 100.5,
            afterMinAsset: 95.25,
            impactScore: 0.15,
            riskLimit: 50.0,
          },
        },
      }),
    );
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    expect(screen.getByText(/Trade accepted — Order order-evt-456/)).toBeInTheDocument();

    // TradeReceipt values
    expect(screen.getByText("100.50")).toBeInTheDocument();
    expect(screen.getByText("95.25")).toBeInTheDocument();
    expect(screen.getByText("15.0%")).toBeInTheDocument();
    expect(screen.getByText("50.00")).toBeInTheDocument();
  });

  // Step 9: TradeReceipt color threshold tests
  it("shows danger color for impact score > 0.5", () => {
    mockUseEventTrade.mockReturnValue(
      defaultMutationState({
        isSuccess: true,
        isIdle: false,
        status: "success",
        data: {
          order: { orderId: "order-1" },
          assetDelta: { beforeMinAsset: 100, afterMinAsset: 40, impactScore: 0.6, riskLimit: 50 },
        },
      }),
    );
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    const impactEl = screen.getByText("60.0%");
    expect(impactEl.style.color).toBe("var(--color-danger)");
  });

  it("shows warning color for impact score > 0.2 and <= 0.5", () => {
    mockUseEventTrade.mockReturnValue(
      defaultMutationState({
        isSuccess: true,
        isIdle: false,
        status: "success",
        data: {
          order: { orderId: "order-2" },
          assetDelta: { beforeMinAsset: 100, afterMinAsset: 70, impactScore: 0.3, riskLimit: 50 },
        },
      }),
    );
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    const impactEl = screen.getByText("30.0%");
    expect(impactEl.style.color).toBe("var(--color-warning, orange)");
  });

  it("shows muted color for impact score <= 0.2", () => {
    mockUseEventTrade.mockReturnValue(
      defaultMutationState({
        isSuccess: true,
        isIdle: false,
        status: "success",
        data: {
          order: { orderId: "order-3" },
          assetDelta: { beforeMinAsset: 100, afterMinAsset: 90, impactScore: 0.1, riskLimit: 50 },
        },
      }),
    );
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    const impactEl = screen.getByText("10.0%");
    expect(impactEl.style.color).toBe("var(--color-text-muted)");
  });

  // Step 10: Error state tests
  it("shows error message when mutation fails with Error", () => {
    mockUseEventTrade.mockReturnValue(
      defaultMutationState({
        isError: true,
        isIdle: false,
        status: "error",
        error: new Error("Insufficient balance"),
      }),
    );
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    expect(screen.getByText("Insufficient balance")).toBeInTheDocument();
  });

  it("shows fallback error message for non-Error errors", () => {
    mockUseEventTrade.mockReturnValue(
      defaultMutationState({
        isError: true,
        isIdle: false,
        status: "error",
        error: "something weird",
      }),
    );
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    expect(screen.getByText("Trade failed")).toBeInTheDocument();
  });

  // Step 11: No-submission guard
  it("does not call mutate when no outcome is selected", () => {
    renderWithProviders(<EventTradePanel market={mockMarket} />);

    // Click trade button without selecting an outcome
    const button = screen.getByRole("button", { name: "Buy ..." });
    fireEvent.click(button);

    expect(mockMutate).not.toHaveBeenCalled();
  });
});
