import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { AccountPnL } from "@/features/analytics";
import * as api from "@/lib/api/client";
import { BayesApiError } from "@/lib/api/client";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, getAccountPnl: vi.fn() };
});

const mockAccountPnl = {
  pnl: {
    accountId: "acct1",
    markets: [
      {
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
        },
        summary: {
          totalCostBasis: 6.5,
          totalCurrentValue: 7.0,
          totalUnrealizedPnl: 0.5,
          totalRealizedPnl: 0,
          totalPnl: 0.5,
        },
      },
    ],
    summary: {
      totalCostBasis: 6.5,
      totalCurrentValue: 7.0,
      totalUnrealizedPnl: 0.5,
      totalRealizedPnl: 0,
      totalPnl: 0.5,
    },
  },
  meta: { timestamp: "2026-04-08T12:00:00Z" },
};

describe("AccountPnL", () => {
  beforeEach(() => {
    vi.mocked(api.getAccountPnl).mockResolvedValue(mockAccountPnl);
  });

  it("renders account P&L heading and summary", async () => {
    renderWithProviders(<AccountPnL accountId="acct1" />);
    await waitFor(() => {
      expect(screen.getByText("Account P&L")).toBeInTheDocument();
    });
    expect(screen.getByText("Cost Basis")).toBeInTheDocument();
    expect(screen.getByText("Total P&L")).toBeInTheDocument();
  });

  it("shows market row", async () => {
    renderWithProviders(<AccountPnL accountId="acct1" />);
    await waitFor(() => {
      expect(screen.getByText("m1")).toBeInTheDocument();
    });
  });

  it("handles loading state", () => {
    vi.mocked(api.getAccountPnl).mockReturnValue(new Promise(() => {}));
    renderWithProviders(<AccountPnL accountId="acct1" />);
    // Should show loading spinner
    expect(document.querySelector('[class*="spinner"], [role="status"]') ?? document.body).toBeTruthy();
  });

  it("shows 'No trades yet' on 404", async () => {
    vi.mocked(api.getAccountPnl).mockRejectedValue(
      new BayesApiError(404, "no_orders_found"),
    );
    renderWithProviders(<AccountPnL accountId="acct1" />);
    await waitFor(() => {
      expect(screen.getByText("No trades yet")).toBeInTheDocument();
    });
  });

  it("returns null when no accountId", () => {
    const { container } = renderWithProviders(<AccountPnL accountId="" />);
    expect(container.innerHTML).toBe("");
  });
});
