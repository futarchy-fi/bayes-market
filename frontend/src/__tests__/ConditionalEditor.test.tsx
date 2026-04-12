import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { ConditionalEditor } from "@/features/trading/ConditionalEditor";
import * as api from "@/lib/api/client";
import type { Market } from "@/lib/api/types";

vi.mock("@/lib/api/client");

const accountId = "acct-editor";

const market: Market = {
  id: "m1",
  title: "Main Market",
  description: "Test",
  variableId: "var1",
  status: "active",
  outcomes: [
    { id: "yes", name: "Yes" },
    { id: "no", name: "No" },
  ],
  marginals: { yes: 0.65, no: 0.35 },
  liquidity: 1000,
  volume: 500,
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-12-31T23:59:59Z",
};

const otherMarketSummary = {
  id: "m2",
  title: "Other Market",
  status: "active" as const,
  liquidity: 500,
  volume: 200,
  expires_at: "2026-12-31T23:59:59Z",
};

const otherMarketDetail = {
  market: {
    id: "m2",
    title: "Other Market",
    description: "Another market",
    variableId: "var2",
    status: "active" as const,
    outcomes: [
      { id: "up", name: "Up" },
      { id: "down", name: "Down" },
    ],
    marginals: { up: 0.5, down: 0.5 },
    liquidity: 500,
    volume: 200,
    created_at: "2026-01-01T00:00:00Z",
    expires_at: "2026-12-31T23:59:59Z",
  },
  meta: { apiVersion: "1.0", timestamp: "2026-04-12T00:00:00Z" },
};

const marketsListResponse = {
  markets: [
    {
      id: "m1",
      title: "Main Market",
      status: "active" as const,
      liquidity: 1000,
      volume: 500,
      expires_at: "2026-12-31T23:59:59Z",
    },
    otherMarketSummary,
  ],
  count: 2,
  meta: {
    apiVersion: "1.0",
    timestamp: "2026-04-12T00:00:00Z",
    filters: { status: null, include_resolved: false },
  },
};

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(
    "bayes-session",
    JSON.stringify({ accountId, agentId: "agent-1" }),
  );
  vi.clearAllMocks();
  vi.stubGlobal("crypto", { randomUUID: () => "uuid-test" });

  vi.mocked(api.listMarkets).mockResolvedValue(marketsListResponse);
  vi.mocked(api.getMarket).mockResolvedValue(otherMarketDetail);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ConditionalEditor", () => {
  it("shows placeholder when session is not configured", () => {
    localStorage.clear();
    renderWithProviders(<ConditionalEditor market={market} />);
    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
  });

  it("renders heading, target outcome, and probability slider", () => {
    renderWithProviders(<ConditionalEditor market={market} />);
    expect(
      screen.getByText("Conditional Probability Edit"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Target Outcome/)).toBeInTheDocument();
    expect(screen.getByText(/New Probability/)).toBeInTheDocument();
  });

  it("shows unconditional button text when no conditions", () => {
    renderWithProviders(<ConditionalEditor market={market} />);
    expect(
      screen.getByRole("button", { name: /Submit Unconditional Edit/ }),
    ).toBeInTheDocument();
  });

  it("shows no-conditions message initially", () => {
    renderWithProviders(<ConditionalEditor market={market} />);
    expect(
      screen.getByText(/No conditions — this is an unconditional edit/),
    ).toBeInTheDocument();
  });

  it("adds a context row and removes it", async () => {
    renderWithProviders(<ConditionalEditor market={market} />);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Add condition/ }),
      ).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));
    expect(screen.queryByText(/No conditions/)).not.toBeInTheDocument();

    // Remove the context row
    fireEvent.click(screen.getByRole("button", { name: "×" }));
    expect(screen.getByText(/No conditions/)).toBeInTheDocument();
  });

  it("context row outcome select is disabled before market selection", async () => {
    renderWithProviders(<ConditionalEditor market={market} />);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Add condition/ }),
      ).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));

    const selects = screen.getAllByRole("combobox");
    // Last select is the context outcome select
    const outcomeSelect = selects[selects.length - 1];
    expect(outcomeSelect).toBeDisabled();
  });

  it("enables context outcome select after market selection", async () => {
    renderWithProviders(<ConditionalEditor market={market} />);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Add condition/ }),
      ).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));

    const selects = screen.getAllByRole("combobox");
    const contextMarketSelect = selects[selects.length - 2]!;

    fireEvent.change(contextMarketSelect, { target: { value: "m2" } });

    await waitFor(() => {
      const updatedSelects = screen.getAllByRole("combobox");
      expect(updatedSelects[updatedSelects.length - 1]).not.toBeDisabled();
    });
  });

  it("changes button text to conditional when context is added", async () => {
    renderWithProviders(<ConditionalEditor market={market} />);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Add condition/ }),
      ).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: /Add condition/ }));
    expect(
      screen.getByRole("button", { name: /Submit Conditional Edit/ }),
    ).toBeInTheDocument();
  });

  it("submits unconditional edit with correct payload", async () => {
    vi.mocked(api.submitProbabilityEdit).mockResolvedValue({
      order: { orderId: "ord-123" },
    } as any);

    renderWithProviders(<ConditionalEditor market={market} />);
    fireEvent.click(
      screen.getByRole("button", { name: /Submit Unconditional Edit/ }),
    );

    await waitFor(() => {
      expect(api.submitProbabilityEdit).toHaveBeenCalledTimes(1);
    });

    const [mktId, payload, session] =
      vi.mocked(api.submitProbabilityEdit).mock.calls[0]!;
    expect(mktId).toBe("m1");
    expect(payload).toMatchObject({
      accountId,
      variableId: "var1",
      target: { kind: "marginal", outcomeId: "yes", probability: 0.5 },
      context: [],
      idempotencyKey: "uuid-test",
    });
    expect(session).toMatchObject({ accountId, agentId: "agent-1" });
  });

  it("shows success message with order ID", async () => {
    vi.mocked(api.submitProbabilityEdit).mockResolvedValue({
      order: { orderId: "ord-456" },
    } as any);

    renderWithProviders(<ConditionalEditor market={market} />);
    fireEvent.click(
      screen.getByRole("button", { name: /Submit Unconditional Edit/ }),
    );

    await waitFor(() => {
      expect(screen.getByText(/ord-456/)).toBeInTheDocument();
    });
  });

  it("shows error message on mutation failure", async () => {
    vi.mocked(api.submitProbabilityEdit).mockRejectedValue(
      new Error("Edit rejected"),
    );

    renderWithProviders(<ConditionalEditor market={market} />);
    fireEvent.click(
      screen.getByRole("button", { name: /Submit Unconditional Edit/ }),
    );

    await waitFor(() => {
      expect(screen.getByText("Edit rejected")).toBeInTheDocument();
    });
  });
});
