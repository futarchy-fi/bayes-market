import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { DiscussionThread } from "@/features/market/DiscussionThread";
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
  useMarketComments: vi.fn(),
  usePostMarketComment: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import { useMarketComments, usePostMarketComment } from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseMarketComments = vi.mocked(useMarketComments);
const mockUsePostMarketComment = vi.mocked(usePostMarketComment);

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

const mockMarketResolved: Market = {
  ...mockMarket,
  id: "mkt-2",
  status: "resolved",
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

// Fake time: 2025-01-15T12:00:00Z
// Comment 1: 1 day ago  → 2025-01-14T12:00:00Z
// Comment 2: 2 hours ago → 2025-01-15T10:00:00Z
const mockComments = [
  {
    commentId: "cmt-1",
    marketId: "mkt-1",
    seq: 1,
    accountId: "alice",
    body: "I think it will rain.",
    createdAt: "2025-01-14T12:00:00Z",
  },
  {
    commentId: "cmt-2",
    marketId: "mkt-1",
    seq: 2,
    accountId: "bob",
    body: "I disagree, forecast looks dry.",
    createdAt: "2025-01-15T10:00:00Z",
  },
];

function defaultQueryState(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      marketId: "mkt-1",
      comments: mockComments,
      pagination: { fromSeq: 0, limit: 50, returned: 2, nextFromSeq: null },
      meta: { apiVersion: "1", timestamp: "2025-01-15T12:00:00Z" },
    },
    isLoading: false,
    isError: false,
    error: null,
    isPending: false,
    isSuccess: true,
    status: "success" as const,
    isFetching: false,
    isRefetching: false,
    failureCount: 0,
    failureReason: null,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    fetchStatus: "idle" as const,
    isStale: false,
    isPlaceholderData: false,
    isFetched: false,
    isFetchedAfterMount: false,
    isLoadingError: false,
    isRefetchError: false,
    isInitialLoading: false,
    errorUpdateCount: 0,
    ...overrides,
  } as unknown as ReturnType<typeof useMarketComments>;
}

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
  } as unknown as ReturnType<typeof usePostMarketComment>;
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2025-01-15T12:00:00Z"));
  vi.clearAllMocks();
  mockUseSession.mockReturnValue(configuredSession);
  mockUseMarketComments.mockReturnValue(defaultQueryState());
  mockUsePostMarketComment.mockReturnValue(defaultMutationState());
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DiscussionThread", () => {
  // Step 4: Loading state
  it("shows loading state when comments are loading", () => {
    mockUseMarketComments.mockReturnValue(
      defaultQueryState({ isLoading: true, isSuccess: false, data: undefined }),
    );
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    expect(screen.getByText("Loading discussion...")).toBeInTheDocument();
  });

  // Step 5: Error state
  it("shows error state when comments fail to load", () => {
    mockUseMarketComments.mockReturnValue(
      defaultQueryState({
        isError: true,
        isSuccess: false,
        data: undefined,
        error: new Error("Network error"),
      }),
    );
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    expect(screen.getByText("Network error")).toBeInTheDocument();
  });

  // Step 6: Empty state
  it("shows empty state when no comments exist", () => {
    mockUseMarketComments.mockReturnValue(
      defaultQueryState({
        data: {
          marketId: "mkt-1",
          comments: [],
          pagination: { fromSeq: 0, limit: 50, returned: 0, nextFromSeq: null },
          meta: { apiVersion: "1", timestamp: "2025-01-15T12:00:00Z" },
        },
      }),
    );
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    expect(screen.getByText("No comments yet.")).toBeInTheDocument();
  });

  // Step 7: Renders comments with details
  it("renders comments with author, sequence number, relative time, and body", () => {
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    // Comment 1: alice, #1, 1d ago
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("1d ago")).toBeInTheDocument();
    expect(screen.getByText("I think it will rain.")).toBeInTheDocument();

    // Comment 2: bob, #2, 2h ago
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    expect(screen.getByText("2h ago")).toBeInTheDocument();
    expect(screen.getByText("I disagree, forecast looks dry.")).toBeInTheDocument();
  });

  // Step 8: Comment count badge
  it("displays comment count badge with correct singular/plural", () => {
    // 2 comments → "2 comments"
    renderWithProviders(<DiscussionThread market={mockMarket} />);
    expect(screen.getByText("2 comments")).toBeInTheDocument();
  });

  it("displays singular comment count", () => {
    mockUseMarketComments.mockReturnValue(
      defaultQueryState({
        data: {
          marketId: "mkt-1",
          comments: [mockComments[0]],
          pagination: { fromSeq: 0, limit: 50, returned: 1, nextFromSeq: null },
          meta: { apiVersion: "1", timestamp: "2025-01-15T12:00:00Z" },
        },
      }),
    );
    renderWithProviders(<DiscussionThread market={mockMarket} />);
    expect(screen.getByText("1 comment")).toBeInTheDocument();
  });

  // Step 9: Unconfigured session
  it("shows setup message when session is not configured", () => {
    mockUseSession.mockReturnValue(unconfiguredSession);
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  // Step 10: Composer form visible
  it("renders composer form when session is configured and market is active", () => {
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    expect(
      screen.getByPlaceholderText("Share your thesis, assumptions, or trade rationale."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Post Comment" })).toBeInTheDocument();
    expect(screen.getByText("2000 characters remaining")).toBeInTheDocument();
  });

  // Step 11: Read-only for resolved market
  it("shows read-only message when market is not active", () => {
    renderWithProviders(<DiscussionThread market={mockMarketResolved} />);

    expect(
      screen.getByText("Discussion is read-only because this market is resolved."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  // Step 12: Disabled submit when empty
  it("disables submit button when textarea is empty or whitespace-only", () => {
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    const button = screen.getByRole("button", { name: "Post Comment" });
    expect(button).toBeDisabled();

    // Type whitespace only
    const textarea = screen.getByPlaceholderText(
      "Share your thesis, assumptions, or trade rationale.",
    );
    fireEvent.change(textarea, { target: { value: "   " } });
    expect(button).toBeDisabled();
  });

  // Step 13: Submit and clear
  it("submits comment with correct payload and clears form on success", () => {
    mockMutate.mockImplementation((_vars: unknown, opts?: { onSuccess?: () => void }) => {
      opts?.onSuccess?.();
    });

    renderWithProviders(<DiscussionThread market={mockMarket} />);

    const textarea = screen.getByPlaceholderText(
      "Share your thesis, assumptions, or trade rationale.",
    );
    fireEvent.change(textarea, { target: { value: "  My analysis here  " } });

    const form = textarea.closest("form")!;
    fireEvent.submit(form);

    expect(mockMutate).toHaveBeenCalledTimes(1);
    const call = mockMutate.mock.calls[0]![0];
    expect(call.payload.accountId).toBe("acc-123");
    expect(call.payload.body).toBe("My analysis here");
    expect(call.payload.idempotencyKey).toBeDefined();
    expect(call.session).toEqual({ accountId: "acc-123", agentId: "agent-1" });

    // Textarea cleared after onSuccess
    expect(textarea).toHaveValue("");
  });

  // Step 14: Pending mutation
  it("shows Posting... and disables button when mutation is pending", () => {
    mockUsePostMarketComment.mockReturnValue(
      defaultMutationState({ isPending: true, isIdle: false, status: "pending" }),
    );
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    const button = screen.getByRole("button", { name: "Posting..." });
    expect(button).toBeDisabled();
  });

  // Step 15: Mutation error
  it("shows error message when comment post fails", () => {
    mockUsePostMarketComment.mockReturnValue(
      defaultMutationState({
        isError: true,
        isIdle: false,
        status: "error",
        error: new Error("Server error"),
      }),
    );
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    expect(screen.getByText("Server error")).toBeInTheDocument();
  });

  // Step 16: Character count
  it("updates character count as user types", () => {
    renderWithProviders(<DiscussionThread market={mockMarket} />);

    const textarea = screen.getByPlaceholderText(
      "Share your thesis, assumptions, or trade rationale.",
    );
    fireEvent.change(textarea, { target: { value: "Hello world" } });

    // 2000 - 11 = 1989
    expect(screen.getByText("1989 characters remaining")).toBeInTheDocument();
  });
});
