import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { VariableRow } from "@/features/assumptions/VariableRow";
import { AssumptionProvider, useAssumptions } from "@/features/assumptions/AssumptionContext";
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
  useMarket: vi.fn(),
  useProbabilityEdit: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import { useMarket, useProbabilityEdit } from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseMarket = vi.mocked(useMarket);
const mockUseProbabilityEdit = vi.mocked(useProbabilityEdit);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const targetMarket: Market = {
  id: "mkt-target",
  title: "Will it rain tomorrow?",
  description: "Rain forecast market",
  variableId: "var-target",
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

const otherMarket: Market = {
  id: "mkt-other",
  title: "Will the sun shine?",
  description: "Sun forecast market",
  variableId: "mkt-other", // matches id so hasAssumption(m.id) finds the stored assumption
  status: "active",
  outcomes: [
    { id: "out-sun-yes", name: "Sunny" },
    { id: "out-sun-no", name: "Cloudy" },
  ],
  marginals: { "out-sun-yes": 0.7, "out-sun-no": 0.3 },
  liquidity: 800,
  volume: 300,
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
// Helpers
// ---------------------------------------------------------------------------

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

/**
 * Render VariableRow wrapped in a real AssumptionProvider with optional Seeder.
 */
function renderVariableRow(
  { marketId = otherMarket.id, target = targetMarket, initialAssumptions = [] as Array<{ variableId: string; outcomeId: string; label: string }> } = {},
) {
  function Wrapper() {
    return (
      <AssumptionProvider>
        <Seeder assumptions={initialAssumptions} />
        <VariableRow marketId={marketId} targetMarket={target} />
      </AssumptionProvider>
    );
  }

  return renderWithProviders(<Wrapper />);
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSession.mockReturnValue(configuredSession);
  mockUseProbabilityEdit.mockReturnValue(defaultMutationState());
  // Default: useMarket returns the otherMarket
  mockUseMarket.mockReturnValue({
    data: { market: otherMarket, meta: { requestId: "r1" } },
    isLoading: false,
    isError: false,
    error: null,
  } as unknown as ReturnType<typeof useMarket>);
});

// ---------------------------------------------------------------------------
// Tests: Rendering
// ---------------------------------------------------------------------------

describe("VariableRow", () => {
  describe("rendering", () => {
    it("returns null when useMarket has no data", () => {
      mockUseMarket.mockReturnValue({
        data: undefined,
        isLoading: true,
        isError: false,
        error: null,
      } as unknown as ReturnType<typeof useMarket>);

      renderVariableRow();
      // VariableRow returns null — no market title or outcomes rendered
      expect(screen.queryByText(/Will the sun shine/)).not.toBeInTheDocument();
      expect(screen.queryByText("Assume")).not.toBeInTheDocument();
    });

    it("renders market title and outcomes with probabilities", () => {
      renderVariableRow();

      expect(screen.getByText(/Will the sun shine\?/)).toBeInTheDocument();
      expect(screen.getByText(/Sunny: 70\.0%/)).toBeInTheDocument();
      expect(screen.getByText(/Cloudy: 30\.0%/)).toBeInTheDocument();
    });

    it("renders '(current)' label for target market", () => {
      mockUseMarket.mockReturnValue({
        data: { market: targetMarket, meta: { requestId: "r1" } },
        isLoading: false,
        isError: false,
        error: null,
      } as unknown as ReturnType<typeof useMarket>);

      renderVariableRow({ marketId: targetMarket.id, target: targetMarket });

      expect(screen.getByText("(current)")).toBeInTheDocument();
    });

    it("does not render '(current)' for non-target market", () => {
      renderVariableRow();

      expect(screen.queryByText("(current)")).not.toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Tests: Assumption toggle
  // ---------------------------------------------------------------------------

  describe("assumption toggle", () => {
    it("renders Assume button for each outcome on non-target market", () => {
      renderVariableRow();

      const assumeButtons = screen.getAllByText("Assume");
      expect(assumeButtons).toHaveLength(2);
    });

    it("clicking Assume adds assumption and shows badge and button text change", () => {
      renderVariableRow();

      const assumeButtons = screen.getAllByText("Assume");
      fireEvent.click(assumeButtons[0]!);

      expect(screen.getByText(/ASSUMED: out-sun-yes/)).toBeInTheDocument();
      expect(screen.getByText("✓ Assumed")).toBeInTheDocument();
    });

    it("clicking assumed button again removes assumption", () => {
      renderVariableRow();

      // Assume first outcome
      const assumeButtons = screen.getAllByText("Assume");
      fireEvent.click(assumeButtons[0]!);

      // Verify assumed
      expect(screen.getByText("✓ Assumed")).toBeInTheDocument();

      // Click again to remove
      fireEvent.click(screen.getByText("✓ Assumed"));

      // Should revert to two "Assume" buttons, no badge
      expect(screen.queryByText(/ASSUMED:/)).not.toBeInTheDocument();
      expect(screen.getAllByText("Assume")).toHaveLength(2);
    });

    it("does NOT render Assume button when marketId === targetMarket.id", () => {
      mockUseMarket.mockReturnValue({
        data: { market: targetMarket, meta: { requestId: "r1" } },
        isLoading: false,
        isError: false,
        error: null,
      } as unknown as ReturnType<typeof useMarket>);

      renderVariableRow({ marketId: targetMarket.id, target: targetMarket });

      expect(screen.queryByText("Assume")).not.toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Tests: Edit flow
  // ---------------------------------------------------------------------------

  describe("edit flow", () => {
    it("renders Edit button when session is configured", () => {
      renderVariableRow();

      expect(screen.getAllByText("Edit")).toHaveLength(2);
    });

    it("hides Edit button when session is not configured", () => {
      mockUseSession.mockReturnValue(unconfiguredSession);
      renderVariableRow();

      expect(screen.queryByText("Edit")).not.toBeInTheDocument();
    });

    it("clicking Edit shows slider and Set/Cancel buttons", () => {
      renderVariableRow();

      fireEvent.click(screen.getAllByText("Edit")[0]!);

      expect(screen.getByRole("slider")).toBeInTheDocument();
      expect(screen.getByText("Set")).toBeInTheDocument();
      expect(screen.getByText("✕")).toBeInTheDocument();
    });

    it("changing slider updates displayed probability", () => {
      renderVariableRow();

      fireEvent.click(screen.getAllByText("Edit")[0]!);

      const slider = screen.getByRole("slider");
      fireEvent.change(slider, { target: { value: "0.85" } });

      expect(screen.getByText(/Sunny: 85\.0%/)).toBeInTheDocument();
    });

    it("clicking Set calls mutation.mutate with correct payload for non-target market", () => {
      renderVariableRow();

      fireEvent.click(screen.getAllByText("Edit")[0]!);

      const slider = screen.getByRole("slider");
      fireEvent.change(slider, { target: { value: "0.8" } });

      fireEvent.click(screen.getByText("Set"));

      expect(mockMutate).toHaveBeenCalledTimes(1);
      const call = mockMutate.mock.calls[0]![0];
      expect(call.payload.accountId).toBe("acc-123");
      expect(call.payload.variableId).toBe("mkt-other"); // uses m.variableId
      expect(call.payload.target).toEqual({
        kind: "marginal",
        outcomeId: "out-sun-yes",
        probability: 0.8,
      });
      expect(call.payload.context).toBeDefined();
      expect(call.payload.idempotencyKey).toBeDefined();
      expect(call.session).toEqual({ accountId: "acc-123", agentId: "agent-1" });
    });

    it("uses targetMarket.variableId when isTargetMarket", () => {
      mockUseMarket.mockReturnValue({
        data: { market: targetMarket, meta: { requestId: "r1" } },
        isLoading: false,
        isError: false,
        error: null,
      } as unknown as ReturnType<typeof useMarket>);

      renderVariableRow({ marketId: targetMarket.id, target: targetMarket });

      fireEvent.click(screen.getAllByText("Edit")[0]!);
      fireEvent.click(screen.getByText("Set"));

      expect(mockMutate).toHaveBeenCalledTimes(1);
      const call = mockMutate.mock.calls[0]![0];
      expect(call.payload.variableId).toBe("var-target"); // uses targetMarket.variableId
    });

    it("clicking Cancel hides slider", () => {
      renderVariableRow();

      fireEvent.click(screen.getAllByText("Edit")[0]!);
      expect(screen.getByRole("slider")).toBeInTheDocument();

      fireEvent.click(screen.getByText("✕"));
      expect(screen.queryByRole("slider")).not.toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Tests: Mutation feedback
  // ---------------------------------------------------------------------------

  describe("mutation feedback", () => {
    it("Set button shows '…' and is disabled when isPending", () => {
      mockUseProbabilityEdit.mockReturnValue(
        defaultMutationState({ isPending: true, isIdle: false, status: "pending" }),
      );
      renderVariableRow();

      fireEvent.click(screen.getAllByText("Edit")[0]!);

      const setButton = screen.getByText("…");
      expect(setButton).toBeDisabled();
    });

    it("renders success message with orderId", () => {
      mockUseProbabilityEdit.mockReturnValue(
        defaultMutationState({
          isSuccess: true,
          isIdle: false,
          status: "success",
          data: { order: { orderId: "order-xyz-789" } },
        }),
      );
      renderVariableRow();

      expect(screen.getByText(/Edit accepted: order-xyz-789/)).toBeInTheDocument();
    });

    it("renders error.message for Error instances", () => {
      mockUseProbabilityEdit.mockReturnValue(
        defaultMutationState({
          isError: true,
          isIdle: false,
          status: "error",
          error: new Error("Insufficient balance"),
        }),
      );
      renderVariableRow();

      expect(screen.getByText("Insufficient balance")).toBeInTheDocument();
    });

    it("renders 'Edit failed' for non-Error", () => {
      mockUseProbabilityEdit.mockReturnValue(
        defaultMutationState({
          isError: true,
          isIdle: false,
          status: "error",
          error: "something went wrong",
        }),
      );
      renderVariableRow();

      expect(screen.getByText("Edit failed")).toBeInTheDocument();
    });
  });
});
