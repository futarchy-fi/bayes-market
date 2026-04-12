import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { VariableRow } from "@/features/assumptions/VariableRow";
import { AssumptionProvider } from "@/features/assumptions/AssumptionContext";
import * as api from "@/lib/api/client";
import type { Market } from "@/lib/api/types";

vi.mock("@/lib/api/client");

const accountId = "acct-viewer";

const targetMarket: Market = {
  id: "m-target",
  title: "Target Market",
  description: "The target",
  variableId: "m-target",
  status: "active",
  outcomes: [
    { id: "yes", name: "Yes" },
    { id: "no", name: "No" },
  ],
  marginals: { yes: 0.6, no: 0.4 },
  liquidity: 1000,
  volume: 500,
  created_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-12-31T23:59:59Z",
};

const rowMarketData = {
  market: {
    id: "m-row",
    title: "Row Market",
    description: "A related market",
    variableId: "m-row",
    status: "active" as const,
    outcomes: [
      { id: "up", name: "Up" },
      { id: "down", name: "Down" },
    ],
    marginals: { up: 0.7, down: 0.3 },
    liquidity: 500,
    volume: 200,
    created_at: "2026-01-01T00:00:00Z",
    expires_at: "2026-12-31T23:59:59Z",
  },
  meta: { apiVersion: "1.0", timestamp: "2026-04-12T00:00:00Z" },
};

function renderVariableRow(
  marketId: string = "m-row",
  target: Market = targetMarket,
) {
  return renderWithProviders(
    <AssumptionProvider>
      <VariableRow marketId={marketId} targetMarket={target} />
    </AssumptionProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(
    "bayes-session",
    JSON.stringify({ accountId, agentId: "agent-1" }),
  );
  vi.clearAllMocks();
  vi.stubGlobal("crypto", { randomUUID: () => "uuid-var" });
  vi.mocked(api.getMarket).mockResolvedValue(rowMarketData);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("VariableRow", () => {
  it("returns null when market data is not loaded", () => {
    vi.mocked(api.getMarket).mockReturnValue(new Promise(() => {}));
    const { container } = renderVariableRow();
    expect(container).toBeEmptyDOMElement();
  });

  it("displays market title and outcome probability bars", async () => {
    renderVariableRow();
    await waitFor(() => {
      expect(screen.getByText("Row Market")).toBeInTheDocument();
    });
    expect(screen.getByText(/Up: 70\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/Down: 30\.0%/)).toBeInTheDocument();
  });

  it("shows assume buttons for non-target market", async () => {
    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Assume" })).toHaveLength(2);
    });
  });

  it("toggles assumption on click", async () => {
    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Assume" })).toHaveLength(2);
    });

    // Assume "Up"
    fireEvent.click(screen.getAllByRole("button", { name: "Assume" })[0]!);
    expect(screen.getByText(/ASSUMED: up/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Assumed/ }),
    ).toBeInTheDocument();

    // Unassume
    fireEvent.click(screen.getByRole("button", { name: /Assumed/ }));
    expect(screen.queryByText(/ASSUMED:/)).not.toBeInTheDocument();
  });

  it("shows edit buttons when session is configured", async () => {
    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
    });
  });

  it("hides edit buttons when session is not configured", async () => {
    localStorage.clear();
    renderVariableRow();
    await waitFor(() => {
      expect(screen.getByText("Row Market")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("opens inline edit slider on Edit click", async () => {
    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    expect(screen.getByRole("slider")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set" })).toBeInTheDocument();
  });

  it("cancels edit on cancel click", async () => {
    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    expect(screen.getByRole("slider")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "✕" }));
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  });

  it("submits edit with correct payload", async () => {
    vi.mocked(api.submitProbabilityEdit).mockResolvedValue({
      order: { orderId: "ord-edit" },
    } as any);

    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Set" }));

    await waitFor(() => {
      expect(api.submitProbabilityEdit).toHaveBeenCalledTimes(1);
    });

    const [mktId, payload] =
      vi.mocked(api.submitProbabilityEdit).mock.calls[0]!;
    expect(mktId).toBe("m-target");
    expect(payload).toMatchObject({
      accountId,
      variableId: "m-row",
      target: { kind: "marginal", outcomeId: "up", probability: 0.7 },
      context: [],
      idempotencyKey: "uuid-var",
    });
  });

  it("includes contextPayload from assumptions in mutation", async () => {
    vi.mocked(api.submitProbabilityEdit).mockResolvedValue({
      order: { orderId: "ord-ctx" },
    } as any);

    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Assume" })).toHaveLength(2);
    });

    // Assume "Up" first
    fireEvent.click(screen.getAllByRole("button", { name: "Assume" })[0]!);
    expect(screen.getByText(/ASSUMED: up/)).toBeInTheDocument();

    // Then edit
    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Set" }));

    await waitFor(() => {
      expect(api.submitProbabilityEdit).toHaveBeenCalledTimes(1);
    });

    const [, payload] =
      vi.mocked(api.submitProbabilityEdit).mock.calls[0]!;
    expect(payload.context).toEqual([
      { variableId: "m-row", outcomeId: "up" },
    ]);
  });

  it("shows success message with order ID", async () => {
    vi.mocked(api.submitProbabilityEdit).mockResolvedValue({
      order: { orderId: "ord-success" },
    } as any);

    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Set" }));

    await waitFor(() => {
      expect(screen.getByText(/ord-success/)).toBeInTheDocument();
    });
  });

  it("shows error message on mutation failure", async () => {
    vi.mocked(api.submitProbabilityEdit).mockRejectedValue(
      new Error("Edit failed badly"),
    );

    renderVariableRow();
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Set" }));

    await waitFor(() => {
      expect(screen.getByText("Edit failed badly")).toBeInTheDocument();
    });
  });

  it("shows '(current)' label for target market", async () => {
    vi.mocked(api.getMarket).mockResolvedValue({
      market: targetMarket,
      meta: { apiVersion: "1.0", timestamp: "2026-04-12T00:00:00Z" },
    });
    renderVariableRow("m-target", targetMarket);

    await waitFor(() => {
      expect(screen.getByText("(current)")).toBeInTheDocument();
    });
  });

  it("does not show assume button for target market", async () => {
    vi.mocked(api.getMarket).mockResolvedValue({
      market: targetMarket,
      meta: { apiVersion: "1.0", timestamp: "2026-04-12T00:00:00Z" },
    });
    renderVariableRow("m-target", targetMarket);

    await waitFor(() => {
      expect(screen.getByText("Target Market")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: "Assume" }),
    ).not.toBeInTheDocument();
  });
});
