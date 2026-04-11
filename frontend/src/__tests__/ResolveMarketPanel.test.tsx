import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { ResolveMarketPanel } from "@/features/market/ResolveMarketPanel";
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
  useResolveMarket: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import { useResolveMarket } from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseResolveMarket = vi.mocked(useResolveMarket);

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
  } as unknown as ReturnType<typeof useResolveMarket>;
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSession.mockReturnValue(configuredSession);
  mockUseResolveMarket.mockReturnValue(defaultMutationState());
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ResolveMarketPanel", () => {
  // -------------------------------------------------------------------------
  // Guard clause tests
  // -------------------------------------------------------------------------

  describe("guard clauses", () => {
    it("shows resolved summary with resolution string", () => {
      const resolved: Market = { ...mockMarket, status: "resolved", resolution: "Yes" };
      renderWithProviders(<ResolveMarketPanel market={resolved} />);

      expect(screen.getByText("Resolved")).toBeInTheDocument();
      expect(screen.getByText(/Outcome: Yes/)).toBeInTheDocument();
    });

    it("shows resolved summary with resolutionProbabilities", () => {
      const resolved: Market = {
        ...mockMarket,
        status: "resolved",
        resolutionProbabilities: { "out-yes": 0.7, "out-no": 0.3 },
      };
      renderWithProviders(<ResolveMarketPanel market={resolved} />);

      expect(screen.getByText("Resolved")).toBeInTheDocument();
      expect(screen.getByText(/out-yes 70\.0%, out-no 30\.0%/)).toBeInTheDocument();
    });

    it("shows resolved summary with neither resolution nor probabilities", () => {
      const resolved: Market = { ...mockMarket, status: "resolved" };
      renderWithProviders(<ResolveMarketPanel market={resolved} />);

      expect(screen.getByText("Resolved")).toBeInTheDocument();
      expect(screen.getByText(/Resolution finalized/)).toBeInTheDocument();
    });

    it("returns null for draft status market", () => {
      const draft: Market = { ...mockMarket, status: "draft" };
      const { container } = renderWithProviders(<ResolveMarketPanel market={draft} />);

      expect(container.innerHTML).toBe("");
    });

    it("returns null when no accountId", () => {
      mockUseSession.mockReturnValue(unconfiguredSession);
      const { container } = renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      expect(container.innerHTML).toBe("");
    });
  });

  // -------------------------------------------------------------------------
  // Resolve form rendering
  // -------------------------------------------------------------------------

  describe("resolve form rendering", () => {
    it("renders heading, select with placeholder and outcome options, and disabled resolve button", () => {
      renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      expect(screen.getByText("Resolve Market")).toBeInTheDocument();

      const select = screen.getByRole("combobox");
      expect(select).toBeInTheDocument();
      expect(screen.getByText("Select winning outcome...")).toBeInTheDocument();
      expect(screen.getByText("Yes (out-yes)")).toBeInTheDocument();
      expect(screen.getByText("No (out-no)")).toBeInTheDocument();

      const resolveBtn = screen.getByRole("button", { name: "Resolve" });
      expect(resolveBtn).toBeDisabled();
    });
  });

  // -------------------------------------------------------------------------
  // Two-step confirmation flow
  // -------------------------------------------------------------------------

  describe("two-step confirmation flow", () => {
    it("shows confirmation UI after selecting outcome and clicking Resolve", () => {
      renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      const select = screen.getByRole("combobox");
      fireEvent.change(select, { target: { value: "out-yes" } });

      const resolveBtn = screen.getByRole("button", { name: "Resolve" });
      fireEvent.click(resolveBtn);

      expect(screen.getByText(/Confirm resolve to/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Yes, Resolve" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    });

    it("calls mutation.mutate with correct payload when clicking Yes, Resolve", () => {
      renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      const select = screen.getByRole("combobox");
      fireEvent.change(select, { target: { value: "out-yes" } });

      fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
      fireEvent.click(screen.getByRole("button", { name: "Yes, Resolve" }));

      expect(mockMutate).toHaveBeenCalledTimes(1);
      const call = mockMutate.mock.calls[0]![0];
      expect(call.payload.accountId).toBe("acc-123");
      expect(call.payload.outcomeId).toBe("out-yes");
      expect(call.session).toEqual({ accountId: "acc-123", agentId: "agent-1" });
    });

    it("returns to initial resolve button state when clicking Cancel", () => {
      renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      const select = screen.getByRole("combobox");
      fireEvent.change(select, { target: { value: "out-yes" } });

      fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
      expect(screen.getByRole("button", { name: "Yes, Resolve" })).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

      expect(screen.queryByRole("button", { name: "Yes, Resolve" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    });

    it("resets confirming state when changing select outcome", () => {
      renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      const select = screen.getByRole("combobox");
      fireEvent.change(select, { target: { value: "out-yes" } });

      fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
      expect(screen.getByRole("button", { name: "Yes, Resolve" })).toBeInTheDocument();

      fireEvent.change(select, { target: { value: "out-no" } });

      expect(screen.queryByRole("button", { name: "Yes, Resolve" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Resolve" })).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Mutation state tests
  // -------------------------------------------------------------------------

  describe("mutation states", () => {
    it("disables Yes, Resolve button and shows Resolving... when isPending", () => {
      const { rerender } = renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      // Enter confirming state while isPending is false
      const select = screen.getByRole("combobox");
      fireEvent.change(select, { target: { value: "out-yes" } });
      fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
      expect(screen.getByRole("button", { name: "Yes, Resolve" })).toBeInTheDocument();

      // Switch to isPending and re-render (preserves internal state)
      mockUseResolveMarket.mockReturnValue(
        defaultMutationState({ isPending: true, isIdle: false, status: "pending" }),
      );
      rerender(<ResolveMarketPanel market={mockMarket} />);

      const btn = screen.getByRole("button", { name: "Resolving..." });
      expect(btn).toBeDisabled();
    });

    it("shows error message when isError", () => {
      mockUseResolveMarket.mockReturnValue(
        defaultMutationState({
          isError: true,
          isIdle: false,
          status: "error",
          error: new Error("Market already resolved"),
        }),
      );
      renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      expect(screen.getByText("Market already resolved")).toBeInTheDocument();
    });

    it("shows success message when isSuccess", () => {
      mockUseResolveMarket.mockReturnValue(
        defaultMutationState({
          isSuccess: true,
          isIdle: false,
          status: "success",
        }),
      );
      renderWithProviders(<ResolveMarketPanel market={mockMarket} />);

      expect(screen.getByText("Market resolved successfully.")).toBeInTheDocument();
    });
  });
});
