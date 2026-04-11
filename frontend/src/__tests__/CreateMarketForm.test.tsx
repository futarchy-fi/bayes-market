import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { CreateMarketForm } from "@/features/market/CreateMarketForm";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockMutate = vi.fn();
const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

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
  useCreateMarket: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import { useCreateMarket } from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseCreateMarket = vi.mocked(useCreateMarket);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  } as unknown as ReturnType<typeof useCreateMarket>;
}

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

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSession.mockReturnValue(configuredSession);
  mockUseCreateMarket.mockReturnValue(defaultMutationState());
});

// ---------------------------------------------------------------------------
// Tests — Existing render tests
// ---------------------------------------------------------------------------

describe("CreateMarketForm", () => {
  it("renders the form heading", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByRole("heading", { name: "Create Market" })).toBeInTheDocument();
  });

  it("renders title and description inputs", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByPlaceholderText(/Will ETH trade/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Additional context/)).toBeInTheDocument();
  });

  it("renders default Yes/No outcomes", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByDisplayValue("yes")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Yes")).toBeInTheDocument();
    expect(screen.getByDisplayValue("no")).toBeInTheDocument();
    expect(screen.getByDisplayValue("No")).toBeInTheDocument();
  });

  it("renders the add outcome button", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByText("+ Add outcome")).toBeInTheDocument();
  });

  it("renders preview section", () => {
    renderWithProviders(<CreateMarketForm />);
    expect(screen.getByText("PREVIEW")).toBeInTheDocument();
    expect(screen.getByText("Untitled market")).toBeInTheDocument();
  });

  it("shows create button", () => {
    renderWithProviders(<CreateMarketForm />);
    const button = screen.getByRole("button", { name: "Create Market" });
    expect(button).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Validation tests
  // -------------------------------------------------------------------------

  describe("validation", () => {
    it("disables submit when title is empty", () => {
      renderWithProviders(<CreateMarketForm />);
      const button = screen.getByRole("button", { name: "Create Market" });
      expect(button).toBeDisabled();
    });

    it("disables submit when expiresAt is empty", () => {
      renderWithProviders(<CreateMarketForm />);
      // Fill title but leave expiresAt empty
      fireEvent.change(screen.getByPlaceholderText(/Will ETH trade/), {
        target: { value: "Test question" },
      });
      const button = screen.getByRole("button", { name: "Create Market" });
      expect(button).toBeDisabled();
    });

    it("disables submit when an outcome has empty id", () => {
      renderWithProviders(<CreateMarketForm />);
      fireEvent.change(screen.getByPlaceholderText(/Will ETH trade/), {
        target: { value: "Test question" },
      });
      // Clear the first outcome ID
      fireEvent.change(screen.getByDisplayValue("yes"), { target: { value: "" } });
      const button = screen.getByRole("button", { name: "Create Market" });
      expect(button).toBeDisabled();
    });

    it("disables submit when an outcome has empty name", () => {
      renderWithProviders(<CreateMarketForm />);
      fireEvent.change(screen.getByPlaceholderText(/Will ETH trade/), {
        target: { value: "Test question" },
      });
      // Clear the first outcome name
      fireEvent.change(screen.getByDisplayValue("Yes"), { target: { value: "" } });
      const button = screen.getByRole("button", { name: "Create Market" });
      expect(button).toBeDisabled();
    });

    it("enables submit when all fields are valid", () => {
      renderWithProviders(<CreateMarketForm />);
      // Fill title
      fireEvent.change(screen.getByPlaceholderText(/Will ETH trade/), {
        target: { value: "Will ETH hit 5k?" },
      });
      // Fill expiresAt — datetime-local input
      const dateInput = document.querySelector('input[type="datetime-local"]')!;
      fireEvent.change(dateInput, { target: { value: "2026-12-31T23:59" } });
      const button = screen.getByRole("button", { name: "Create Market" });
      expect(button).toBeEnabled();
    });
  });

  // -------------------------------------------------------------------------
  // Form interaction tests
  // -------------------------------------------------------------------------

  describe("form interactions", () => {
    it("updates preview text when title is typed", () => {
      renderWithProviders(<CreateMarketForm />);
      expect(screen.getByText("Untitled market")).toBeInTheDocument();
      fireEvent.change(screen.getByPlaceholderText(/Will ETH trade/), {
        target: { value: "My cool market" },
      });
      expect(screen.getByText("My cool market")).toBeInTheDocument();
      expect(screen.queryByText("Untitled market")).not.toBeInTheDocument();
    });

    it("adds a third outcome when clicking + Add outcome", () => {
      renderWithProviders(<CreateMarketForm />);
      const addBtn = screen.getByText("+ Add outcome");
      fireEvent.click(addBtn);
      // Third outcome should appear with default values
      expect(screen.getByDisplayValue("o3")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Option 3")).toBeInTheDocument();
    });

    it("disables remove buttons when exactly 2 outcomes", () => {
      renderWithProviders(<CreateMarketForm />);
      const removeButtons = screen.getAllByRole("button", { name: "×" });
      expect(removeButtons).toHaveLength(2);
      removeButtons.forEach((btn) => expect(btn).toBeDisabled());
    });

    it("removes an outcome when 3+ outcomes exist", () => {
      renderWithProviders(<CreateMarketForm />);
      // Add third outcome
      fireEvent.click(screen.getByText("+ Add outcome"));
      expect(screen.getByDisplayValue("o3")).toBeInTheDocument();
      // Remove buttons should now be enabled
      const removeButtons = screen.getAllByRole("button", { name: "×" });
      expect(removeButtons).toHaveLength(3);
      expect(removeButtons[0]).toBeEnabled();
      // Click remove on first outcome
      fireEvent.click(removeButtons[0]!);
      // Should be back to 2 outcomes — "yes" should be gone
      expect(screen.queryByDisplayValue("yes")).not.toBeInTheDocument();
      expect(screen.getByDisplayValue("no")).toBeInTheDocument();
      expect(screen.getByDisplayValue("o3")).toBeInTheDocument();
    });

    it("sanitizes outcome ID to lowercase alphanumeric + underscore", () => {
      renderWithProviders(<CreateMarketForm />);
      const idInput = screen.getByDisplayValue("yes");
      fireEvent.change(idInput, { target: { value: "Hello World!" } });
      // The component runs .toLowerCase().replace(/[^a-z0-9_]/g, "")
      expect(idInput).toHaveValue("helloworld");
    });
  });

  // -------------------------------------------------------------------------
  // Mutation state rendering tests
  // -------------------------------------------------------------------------

  describe("mutation state rendering", () => {
    it("shows 'Creating…' and disables button when mutation is pending", () => {
      mockUseCreateMarket.mockReturnValue(
        defaultMutationState({ isPending: true, isIdle: false, status: "pending" }),
      );
      renderWithProviders(<CreateMarketForm />);
      const button = screen.getByRole("button", { name: /Creating/ });
      expect(button).toHaveTextContent("Creating…");
      expect(button).toBeDisabled();
    });

    it("shows error message when mutation fails with Error instance", () => {
      mockUseCreateMarket.mockReturnValue(
        defaultMutationState({
          isError: true,
          isIdle: false,
          status: "error",
          error: new Error("Network timeout"),
        }),
      );
      renderWithProviders(<CreateMarketForm />);
      expect(screen.getByText("Network timeout")).toBeInTheDocument();
    });

    it("shows fallback error message when error is not an Error instance", () => {
      mockUseCreateMarket.mockReturnValue(
        defaultMutationState({
          isError: true,
          isIdle: false,
          status: "error",
          error: "something went wrong",
        }),
      );
      renderWithProviders(<CreateMarketForm />);
      expect(screen.getByText("Failed to create market")).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Submission and navigation tests
  // -------------------------------------------------------------------------

  describe("submission and navigation", () => {
    function fillFormAndSubmit() {
      fireEvent.change(screen.getByPlaceholderText(/Will ETH trade/), {
        target: { value: "Will ETH hit 5k?" },
      });
      fireEvent.change(screen.getByPlaceholderText(/Additional context/), {
        target: { value: "Resolution: spot price on Dec 31" },
      });
      const dateInput = document.querySelector('input[type="datetime-local"]')!;
      fireEvent.change(dateInput, { target: { value: "2026-12-31T23:59" } });
      // Submit form directly — fireEvent.click on submit buttons triggers
      // jsdom native constraint validation which blocks datetime-local inputs.
      fireEvent.submit(document.querySelector("form")!);
    }

    it("calls mutate with correct payload on submit", () => {
      renderWithProviders(<CreateMarketForm />);
      fillFormAndSubmit();

      expect(mockMutate).toHaveBeenCalledTimes(1);
      const [args] = mockMutate.mock.calls[0]!;
      expect(args.payload.title).toBe("Will ETH hit 5k?");
      expect(args.payload.description).toBe("Resolution: spot price on Dec 31");
      expect(args.payload.outcomes).toEqual([
        { id: "yes", name: "Yes" },
        { id: "no", name: "No" },
      ]);
      expect(args.payload.expires_at).toBe(new Date("2026-12-31T23:59").toISOString());
      expect(args.payload.liquidity).toBe(10000);
      expect(args.session).toEqual({ accountId: "acc-123", agentId: "agent-1" });
    });

    it("navigates to new market on success", () => {
      renderWithProviders(<CreateMarketForm />);
      fillFormAndSubmit();

      // Extract the onSuccess callback from the mutate call
      const [, options] = mockMutate.mock.calls[0]!;
      options.onSuccess({ market: { id: "test-123" } });

      expect(mockNavigate).toHaveBeenCalledWith("/markets/test-123");
    });

    it("passes session as undefined when accountId is empty", () => {
      mockUseSession.mockReturnValue(unconfiguredSession);
      renderWithProviders(<CreateMarketForm />);
      fillFormAndSubmit();

      expect(mockMutate).toHaveBeenCalledTimes(1);
      const [args] = mockMutate.mock.calls[0]!;
      expect(args.session).toBeUndefined();
    });
  });
});
