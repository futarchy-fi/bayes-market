import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { EventTradePanel } from "@/features/trading/EventTradePanel";
import * as api from "@/lib/api/client";
import type { Market } from "@/lib/api/types";

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return {
    ...actual,
    submitEventTrade: vi.fn(),
  };
});

const accountId = "acct-trader";

const market: Market = {
  id: "m1",
  title: "Election 2026",
  description: "Will the incumbent win?",
  variableId: "election_2026",
  status: "active",
  outcomes: [
    { id: "yes", name: "Yes" },
    { id: "no", name: "No" },
  ],
  marginals: { yes: 0.65, no: 0.35 },
  liquidity: 1000,
  volume: 250,
  created_at: "2026-04-01T00:00:00Z",
  expires_at: "2026-12-31T23:59:59Z",
};

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("bayes-session", JSON.stringify({ accountId, agentId: "agent-1" }));
  vi.clearAllMocks();
  vi.stubGlobal("crypto", { randomUUID: () => "uuid-1" });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EventTradePanel", () => {
  it("renders position-limit details inline when the backend rejects the trade", async () => {
    vi.mocked(api.submitEventTrade).mockRejectedValue(
      new api.BayesApiError(400, "position_limit_exceeded", {
        accountId,
        marketId: "m1",
        outcomeId: "yes",
        side: "buy",
        requestedSize: 2,
        currentNetSize: 99,
        resultingNetSize: 101,
        maxPositionSize: 100,
      }),
    );

    renderWithProviders(<EventTradePanel market={market} />);

    fireEvent.change(screen.getByLabelText("Trade outcome"), { target: { value: "yes" } });
    fireEvent.change(screen.getByLabelText("Position size"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /Buy yes/i }));

    await waitFor(() => {
      expect(api.submitEventTrade).toHaveBeenCalledTimes(1);
    });

    const [marketId, payload, session] = vi.mocked(api.submitEventTrade).mock.calls[0]!;
    expect(marketId).toBe("m1");
    expect(payload).toMatchObject({
      accountId,
      size: 2,
      side: "buy",
      formula: [[{ variableId: "m1", outcomeId: "yes", negated: false }]],
    });
    expect(session).toMatchObject({ accountId, agentId: "agent-1" });

    await waitFor(() => {
      expect(screen.getByText("Position limit exceeded. Requested size 2.00 would move net size from 99.00 to 101.00; max position size is 100.00.")).toBeInTheDocument();
    });
  });
});
