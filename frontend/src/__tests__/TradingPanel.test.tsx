import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { TradingPanel } from "@/features/trading/TradingPanel";
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
  useProbabilityEdit: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import { useProbabilityEdit } from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseProbabilityEdit = vi.mocked(useProbabilityEdit);

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
  } as unknown as ReturnType<typeof useProbabilityEdit>;
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSession.mockReturnValue(configuredSession);
  mockUseProbabilityEdit.mockReturnValue(defaultMutationState());
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TradingPanel", () => {
  it("shows setup message when session is not configured", () => {
    mockUseSession.mockReturnValue(unconfiguredSession);
    renderWithProviders(<TradingPanel market={mockMarket} />);

    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  it("renders trading form when session is configured", () => {
    renderWithProviders(<TradingPanel market={mockMarket} />);

    expect(screen.getByRole("heading", { name: "Probability Edit" })).toBeInTheDocument();

    // Outcome select with options
    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    expect(screen.getByText("Yes (65.0%)")).toBeInTheDocument();
    expect(screen.getByText("No (35.0%)")).toBeInTheDocument();

    // Slider
    expect(screen.getByRole("slider")).toBeInTheDocument();

    // Submit button
    expect(screen.getByRole("button", { name: "Submit Edit" })).toBeInTheDocument();
  });

  it("updates probability display when slider changes", () => {
    renderWithProviders(<TradingPanel market={mockMarket} />);

    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "0.75" } });

    expect(screen.getByText(/75\.0%/)).toBeInTheDocument();
  });

  it("calls mutation.mutate with correct payload on form submission", () => {
    renderWithProviders(<TradingPanel market={mockMarket} />);

    // Change outcome to second option
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "out-no" } });

    // Change probability
    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "0.3" } });

    // Submit
    const button = screen.getByRole("button", { name: "Submit Edit" });
    fireEvent.click(button);

    expect(mockMutate).toHaveBeenCalledTimes(1);
    const call = mockMutate.mock.calls[0]![0];
    expect(call.payload.accountId).toBe("acc-123");
    expect(call.payload.variableId).toBe("var-1");
    expect(call.payload.target).toEqual({
      kind: "marginal",
      outcomeId: "out-no",
      probability: 0.3,
    });
    expect(call.payload.idempotencyKey).toBeDefined();
    expect(call.session).toEqual({ accountId: "acc-123", agentId: "agent-1" });
  });

  it("disables submit button and shows Submitting text when mutation is pending", () => {
    mockUseProbabilityEdit.mockReturnValue(
      defaultMutationState({ isPending: true, isIdle: false, status: "pending" }),
    );
    renderWithProviders(<TradingPanel market={mockMarket} />);

    const button = screen.getByRole("button", { name: /Submitting/ });
    expect(button).toBeDisabled();
  });

  it("shows success message with orderId when mutation succeeds", () => {
    mockUseProbabilityEdit.mockReturnValue(
      defaultMutationState({
        isSuccess: true,
        isIdle: false,
        status: "success",
        data: { order: { orderId: "order-abc-123" } },
      }),
    );
    renderWithProviders(<TradingPanel market={mockMarket} />);

    expect(screen.getByText(/Order accepted: order-abc-123/)).toBeInTheDocument();
  });

  it("shows error message when mutation fails", () => {
    mockUseProbabilityEdit.mockReturnValue(
      defaultMutationState({
        isError: true,
        isIdle: false,
        status: "error",
        error: new Error("Insufficient balance"),
      }),
    );
    renderWithProviders(<TradingPanel market={mockMarket} />);

    expect(screen.getByText("Insufficient balance")).toBeInTheDocument();
  });
});
