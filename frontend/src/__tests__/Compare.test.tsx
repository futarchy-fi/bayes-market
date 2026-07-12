import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Compare from "@/routes/Compare";
import { renderWithProviders } from "./helpers";
import * as api from "@/lib/api/client";
import type { Market, MarketDetailResponse, MarketListResponse } from "@/lib/api/types";

vi.mock("@/lib/api/client");

const meta = { apiVersion: "1.0", timestamp: "2026-07-12T00:00:00Z" };
const summaries: MarketListResponse = {
  markets: [
    { id: "a", title: "Market A title", status: "active", liquidity: 1, volume: 0, expires_at: "2027-01-01" },
    { id: "b", title: "Market B title", status: "active", liquidity: 1, volume: 0, expires_at: "2027-01-01" },
  ],
  count: 2,
  meta,
};

function detail(id: string, variableId: string, yes: number): MarketDetailResponse {
  return {
    market: { id, variableId, title: id, description: "", status: "active", outcomes: [], marginals: { yes, no: 1 - yes }, liquidity: 1, volume: 0, created_at: "2026-01-01", expires_at: "2027-01-01" } satisfies Market,
    meta,
  };
}

describe("Compare", () => {
  beforeEach(() => {
    vi.mocked(api.listMarkets).mockResolvedValue(summaries);
    vi.mocked(api.getMarket).mockImplementation(async (id, context) => {
      if (id === "a") return detail("a", "var-a", 0.4);
      return detail("b", "var-b", context?.[0]?.outcomeId === "yes" ? 0.7 : 0.2);
    });
  });

  it("renders the inferred matrix from deep-linked markets", async () => {
    renderWithProviders(<Compare />, { initialEntries: ["/compare?a=a&b=b"] });

    await waitFor(() => expect(screen.getByRole("heading", { name: "Joint distribution" })).toBeInTheDocument());
    expect(screen.getByLabelText("Market A")).toHaveValue("a");
    expect(screen.getByLabelText("Market B")).toHaveValue("b");
    expect(screen.getAllByText("28.00%")).toHaveLength(1);
    expect(screen.getAllByText("48.00%")).toHaveLength(1);
    expect(screen.getByText("0.500000")).toBeInTheDocument();
    expect(api.getMarket).toHaveBeenCalledWith("a", []);
    expect(api.getMarket).toHaveBeenCalledWith("b", [{ variableId: "var-a", outcomeId: "yes" }]);
    expect(api.getMarket).toHaveBeenCalledWith("b", [{ variableId: "var-a", outcomeId: "no" }]);
  });
});
