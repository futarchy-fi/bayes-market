import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { PnLSummary } from "@/features/analytics";
import * as api from "@/lib/api/client";
import { BayesApiError } from "@/lib/api/client";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, getMarketPnl: vi.fn() };
});

const mockPnl = {
  pnl: {
    marketId: "m1",
    outcomes: {
      yes: {
        outcomeId: "yes",
        netSize: 10,
        costBasis: 6.5,
        currentValue: 7.0,
        unrealizedPnl: 0.5,
        realizedPnl: 0,
        totalPnl: 0.5,
      },
      no: {
        outcomeId: "no",
        netSize: -5,
        costBasis: 3.0,
        currentValue: 2.5,
        unrealizedPnl: -0.5,
        realizedPnl: 0,
        totalPnl: -0.5,
      },
    },
    summary: {
      totalCostBasis: 9.5,
      totalCurrentValue: 9.5,
      totalUnrealizedPnl: 0,
      totalRealizedPnl: 0,
      totalPnl: 0,
    },
  },
  meta: { timestamp: "2026-04-08T12:00:00Z" },
};

describe("PnLSummary", () => {
  beforeEach(() => {
    vi.mocked(api.getMarketPnl).mockResolvedValue(mockPnl);
  });

  it("renders P&L data for outcomes", async () => {
    renderWithProviders(<PnLSummary marketId="m1" accountId="acct1" />);
    await waitFor(() => {
      expect(screen.getByText("P&L Summary")).toBeInTheDocument();
    });
    expect(screen.getByText("yes")).toBeInTheDocument();
    expect(screen.getByText("no")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
  });

  it("shows 'No trades yet' on 404", async () => {
    vi.mocked(api.getMarketPnl).mockRejectedValue(
      new BayesApiError(404, "no_orders_found"),
    );
    renderWithProviders(<PnLSummary marketId="m1" accountId="acct1" />);
    await waitFor(() => {
      expect(screen.getByText("No trades yet")).toBeInTheDocument();
    });
  });

  it("returns null when no accountId", () => {
    const { container } = renderWithProviders(<PnLSummary marketId="m1" accountId="" />);
    expect(container.innerHTML).toBe("");
  });
});
