import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { DiscussionThread } from "@/features/market/DiscussionThread";
import * as api from "@/lib/api/client";
import type { Market, MarketCommentsResponse, MarketComment } from "@/lib/api/types";

vi.mock("@/lib/api/client");

// ---------------------------------------------------------------------------
// Mock data factories
// ---------------------------------------------------------------------------

function makeMarket(overrides: Partial<Market> = {}): Market {
  return {
    id: "m1",
    title: "Will it rain tomorrow?",
    description: "Resolves Yes if it rains.",
    variableId: "rain_tomorrow",
    status: "active",
    outcomes: [
      { id: "yes", name: "Yes" },
      { id: "no", name: "No" },
    ],
    marginals: { yes: 0.6, no: 0.4 },
    liquidity: 10000,
    volume: 5000,
    created_at: "2026-04-01T00:00:00Z",
    expires_at: "2026-12-31T23:59:59Z",
    ...overrides,
  };
}

function makeComment(overrides: Partial<MarketComment> = {}): MarketComment {
  return {
    commentId: "c1",
    marketId: "m1",
    seq: 1,
    accountId: "alice",
    body: "I think yes is underpriced.",
    createdAt: new Date(Date.now() - 5 * 60_000).toISOString(),
    ...overrides,
  };
}

function makeCommentsResponse(
  comments: MarketComment[] = [],
  marketId = "m1",
): MarketCommentsResponse {
  return {
    marketId,
    comments,
    pagination: {
      fromSeq: 0,
      limit: 20,
      returned: comments.length,
      nextFromSeq: null,
    },
    meta: { apiVersion: "1.0", timestamp: "2026-04-11T00:00:00Z" },
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function configureSession() {
  localStorage.setItem(
    "bayes-session",
    JSON.stringify({ accountId: "alice", agentId: "agent-1" }),
  );
}

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DiscussionThread", () => {
  it("renders comment list with author, body, seq, and relative time", async () => {
    configureSession();
    const comments = [
      makeComment({ commentId: "c1", seq: 1, accountId: "alice", body: "First comment" }),
      makeComment({ commentId: "c2", seq: 2, accountId: "bob", body: "Second comment" }),
    ];
    vi.mocked(api.getMarketComments).mockResolvedValue(makeCommentsResponse(comments));

    renderWithProviders(<DiscussionThread market={makeMarket()} />);

    await waitFor(() => {
      expect(screen.getByText("First comment")).toBeInTheDocument();
    });

    expect(screen.getByText("Second comment")).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    // relative time rendered (e.g. "5m ago")
    expect(screen.getAllByText(/ago/)).toHaveLength(2);
  });

  it("shows empty state when no comments", async () => {
    configureSession();
    vi.mocked(api.getMarketComments).mockResolvedValue(makeCommentsResponse([]));

    renderWithProviders(<DiscussionThread market={makeMarket()} />);

    await waitFor(() => {
      expect(screen.getByText("No comments yet.")).toBeInTheDocument();
    });
  });

  it("shows loading state before data resolves", () => {
    configureSession();
    const deferred = createDeferred<MarketCommentsResponse>();
    vi.mocked(api.getMarketComments).mockReturnValue(deferred.promise);

    renderWithProviders(<DiscussionThread market={makeMarket()} />);

    expect(screen.getByText("Loading discussion...")).toBeInTheDocument();
  });

  it("shows error state when query fails", async () => {
    configureSession();
    vi.mocked(api.getMarketComments).mockRejectedValue(
      new Error("Network request failed"),
    );

    renderWithProviders(<DiscussionThread market={makeMarket()} />);

    await waitFor(() => {
      expect(screen.getByText("Network request failed")).toBeInTheDocument();
    });
  });

  it("submits comment via composer form", async () => {
    configureSession();
    vi.mocked(api.getMarketComments).mockResolvedValue(makeCommentsResponse([]));
    vi.mocked(api.submitMarketComment).mockResolvedValue({
      comment: makeComment({ body: "My new comment" }),
      meta: { apiVersion: "1.0", timestamp: "2026-04-11T00:00:00Z" },
    });

    renderWithProviders(<DiscussionThread market={makeMarket()} />);

    await waitFor(() => {
      expect(screen.getByText("No comments yet.")).toBeInTheDocument();
    });

    const textarea = screen.getByPlaceholderText(
      "Share your thesis, assumptions, or trade rationale.",
    );
    fireEvent.change(textarea, { target: { value: "My new comment" } });
    fireEvent.click(screen.getByRole("button", { name: "Post Comment" }));

    await waitFor(() => {
      expect(api.submitMarketComment).toHaveBeenCalledTimes(1);
    });

    const calls = vi.mocked(api.submitMarketComment).mock.calls;
    expect(calls).toHaveLength(1);
    const [marketId, payload] = calls[0]!;
    expect(marketId).toBe("m1");
    expect(payload).toMatchObject({ accountId: "alice", body: "My new comment" });
    expect(payload.idempotencyKey).toBeDefined();
  });

  it("disables composer when market status is not active", async () => {
    configureSession();
    vi.mocked(api.getMarketComments).mockResolvedValue(makeCommentsResponse([]));

    renderWithProviders(
      <DiscussionThread market={makeMarket({ status: "resolved" })} />,
    );

    await waitFor(() => {
      expect(
        screen.getByText("Discussion is read-only because this market is resolved."),
      ).toBeInTheDocument();
    });

    expect(
      screen.queryByPlaceholderText(
        "Share your thesis, assumptions, or trade rationale.",
      ),
    ).not.toBeInTheDocument();
  });

  it("shows character count remaining", async () => {
    configureSession();
    vi.mocked(api.getMarketComments).mockResolvedValue(makeCommentsResponse([]));

    renderWithProviders(<DiscussionThread market={makeMarket()} />);

    await waitFor(() => {
      expect(screen.getByText("2000 characters remaining")).toBeInTheDocument();
    });

    const textarea = screen.getByPlaceholderText(
      "Share your thesis, assumptions, or trade rationale.",
    );
    fireEvent.change(textarea, { target: { value: "Hello" } });

    expect(screen.getByText("1995 characters remaining")).toBeInTheDocument();
  });

  it("disables composer when no session configured", async () => {
    // Do NOT set localStorage
    vi.mocked(api.getMarketComments).mockResolvedValue(makeCommentsResponse([]));

    renderWithProviders(<DiscussionThread market={makeMarket()} />);

    await waitFor(() => {
      expect(
        screen.getByText("Set your Account ID in the header to join the discussion."),
      ).toBeInTheDocument();
    });

    expect(
      screen.queryByPlaceholderText(
        "Share your thesis, assumptions, or trade rationale.",
      ),
    ).not.toBeInTheDocument();
  });
});
