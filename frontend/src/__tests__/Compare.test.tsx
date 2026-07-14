import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Compare from "@/routes/Compare";
import { renderWithProviders } from "./helpers";
import * as api from "@/lib/api/client";
import type { Market, MarketDetailResponse, MarketListResponse, NetworkResponse } from "@/lib/api/types";

vi.mock("@/lib/api/client");

const meta = { apiVersion: "1.0", timestamp: "2026-07-12T00:00:00Z" };
const summaries: MarketListResponse = {
  markets: [
    { id: "a", variableId: "var-a", title: "Market A title", status: "active", liquidity: 1, volume: 0, expires_at: "2027-01-01" },
    { id: "b", variableId: "var-b", title: "Market B title", status: "active", liquidity: 1, volume: 0, expires_at: "2027-01-01" },
    { id: "c-target", variableId: "var-c", title: "Needle market C", status: "active", liquidity: 1, volume: 0, expires_at: "2027-01-01" },
  ],
  count: 3,
  meta,
};

function network(edges: NetworkResponse["edges"] = []): NetworkResponse {
  return { nodes: [], edges, meta };
}

function detail(id: string, variableId: string, yes: number): MarketDetailResponse {
  return {
    market: { id, variableId, title: id, description: "", status: "active", outcomes: [], marginals: { yes, no: 1 - yes }, liquidity: 1, volume: 0, created_at: "2026-01-01", expires_at: "2027-01-01" } satisfies Market,
    meta,
  };
}

describe("Compare", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listMarkets).mockResolvedValue(summaries);
    vi.mocked(api.getNetwork).mockResolvedValue(network());
    vi.mocked(api.getMarket).mockImplementation(async (id, context) => {
      if (id === "a") return detail("a", "var-a", 0.4);
      if (id === "b") return detail("b", "var-b", context?.[0]?.outcomeId === "yes" ? 0.7 : 0.2);
      return detail("c-target", "var-c", context?.[0]?.outcomeId === "yes" ? 0.8 : 0.3);
    });
  });

  it("renders the inferred matrix from deep-linked markets", async () => {
    renderWithProviders(<Compare />, { initialEntries: ["/compare?a=a&b=b"] });

    await waitFor(() => expect(screen.getByRole("heading", { name: "Joint distribution" })).toBeInTheDocument());
    expect(screen.getByLabelText("Market A")).toHaveValue("Market A title");
    expect(screen.getByLabelText("Market B")).toHaveValue("Market B title");
    expect(screen.getAllByText("28.00%")).toHaveLength(1);
    expect(screen.getAllByText("48.00%")).toHaveLength(1);
    expect(screen.getByText("0.500000")).toBeInTheDocument();
    expect(api.getMarket).toHaveBeenCalledWith("a", []);
    expect(api.getMarket).toHaveBeenCalledWith("b", [{ variableId: "var-a", outcomeId: "yes" }]);
    expect(api.getMarket).toHaveBeenCalledWith("b", [{ variableId: "var-a", outcomeId: "no" }]);
  });

  it("filters options case-insensitively by title and id", async () => {
    renderWithProviders(<Compare />, { initialEntries: ["/compare?a=a&b=b"] });
    const picker = await screen.findByLabelText("Market B");

    fireEvent.focus(picker);
    fireEvent.change(picker, { target: { value: "nEeDlE" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "Needle market C" })).toBeInTheDocument();

    fireEvent.change(picker, { target: { value: "C-TARGET" } });
    expect(screen.getByRole("option", { name: "Needle market C" })).toBeInTheDocument();
  });

  it("selects a filtered market with Enter and updates the comparison", async () => {
    renderWithProviders(<Compare />, { initialEntries: ["/compare?a=a&b=b"] });
    const picker = await screen.findByLabelText("Market B");

    fireEvent.focus(picker);
    fireEvent.change(picker, { target: { value: "needle" } });
    fireEvent.keyDown(picker, { key: "Enter" });

    await waitFor(() => expect(picker).toHaveValue("Needle market C"));
    expect(api.getMarket).toHaveBeenCalledWith("c-target", [{ variableId: "var-a", outcomeId: "yes" }]);
  });

  it("selects a filtered market by click and updates the comparison", async () => {
    renderWithProviders(<Compare />, { initialEntries: ["/compare?a=a&b=b"] });
    const picker = await screen.findByLabelText("Market B");

    fireEvent.focus(picker);
    fireEvent.change(picker, { target: { value: "needle" } });
    fireEvent.click(screen.getByRole("option", { name: "Needle market C" }));

    await waitFor(() => expect(picker).toHaveValue("Needle market C"));
    expect(api.getMarket).toHaveBeenCalledWith("c-target", [{ variableId: "var-a", outcomeId: "no" }]);
  });

  it("renders graph neighbors and uses a neighbor chip for Market B", async () => {
    vi.mocked(api.getNetwork).mockResolvedValue(network([
      { from: "a", to: "c-target", fromVariableId: "var-a", toVariableId: "var-c" },
    ]));
    renderWithProviders(<Compare />, { initialEntries: ["/compare?a=a&b=b"] });

    fireEvent.click(await screen.findByRole("button", { name: "Needle market C" }));

    await waitFor(() => expect(screen.getByLabelText("Market B")).toHaveValue("Needle market C"));
  });

  it("defaults Market B to Market A's first graph neighbor when b is absent", async () => {
    vi.mocked(api.getNetwork).mockResolvedValue(network([
      { from: "c-target", to: "a", fromVariableId: "var-c", toVariableId: "var-a" },
    ]));
    renderWithProviders(<Compare />, { initialEntries: ["/compare?a=a"] });

    await waitFor(() => expect(screen.getByLabelText("Market B")).toHaveValue("Needle market C"));
    expect(api.getMarket).toHaveBeenCalledWith("c-target", [{ variableId: "var-a", outcomeId: "yes" }]);
  });
});
