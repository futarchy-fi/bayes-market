import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import Analytics from "@/routes/Analytics";
import * as api from "@/lib/api/client";
import type { MarketAnalyticsResponse, MarketListResponse } from "@/lib/api/types";

vi.mock("@/lib/api/client");

const mockMeta = { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" };

const mockMarkets: MarketListResponse = {
  markets: [
    { id: "m1", title: "ETH Price > $3000", status: "active", liquidity: 150000, volume: 45000, expires_at: "2026-12-31T23:59:59Z" },
    { id: "m2", title: "BTC ETF Approval", status: "resolved", liquidity: 89000, volume: 23000, expires_at: "2026-03-14T23:59:59Z" },
  ],
  count: 2,
  meta: mockMeta,
};

const mockAnalytics: MarketAnalyticsResponse = {
  marketId: "m1",
  summary: {
    totalTrades: 42,
    totalVolume: 12500,
    uniqueTraders: 8,
    bucketInterval: "day",
    lastUpdated: "2026-04-08T12:00:00Z",
  },
  priceSeries: [
    {
      outcomeId: "o1",
      outcomeName: "Yes",
      points: [
        { seq: 1, emittedAt: "2026-04-06T00:00:00Z", probability: 0.4 },
        { seq: 2, emittedAt: "2026-04-07T00:00:00Z", probability: 0.55 },
        { seq: 3, emittedAt: "2026-04-08T00:00:00Z", probability: 0.62 },
      ],
    },
    {
      outcomeId: "o2",
      outcomeName: "No",
      points: [
        { seq: 1, emittedAt: "2026-04-06T00:00:00Z", probability: 0.6 },
        { seq: 2, emittedAt: "2026-04-07T00:00:00Z", probability: 0.45 },
        { seq: 3, emittedAt: "2026-04-08T00:00:00Z", probability: 0.38 },
      ],
    },
  ],
  volumeBuckets: [
    { bucketStart: "2026-04-06T00:00:00Z", bucketEnd: "2026-04-07T00:00:00Z", tradeCount: 10, volume: 3000 },
    { bucketStart: "2026-04-07T00:00:00Z", bucketEnd: "2026-04-08T00:00:00Z", tradeCount: 15, volume: 5000 },
    { bucketStart: "2026-04-08T00:00:00Z", bucketEnd: "2026-04-09T00:00:00Z", tradeCount: 17, volume: 4500 },
  ],
  topTraders: [
    { accountId: "trader-1", tradeCount: 12, volume: 4000 },
    { accountId: "trader-2", tradeCount: 8, volume: 3500 },
  ],
  meta: mockMeta,
};

describe("Analytics", () => {
  beforeEach(() => {
    vi.mocked(api.listMarkets).mockResolvedValue(mockMarkets);
    vi.mocked(api.getMarketAnalytics).mockResolvedValue(mockAnalytics);
    vi.mocked(api.getAccountPnl).mockRejectedValue(new Error("no account"));
    localStorage.clear();
  });

  it("shows loading state", () => {
    vi.mocked(api.listMarkets).mockReturnValue(new Promise(() => {}));
    const { container } = renderWithProviders(<Analytics />);
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("shows error state", async () => {
    vi.mocked(api.listMarkets).mockRejectedValue(new Error("Network failure"));
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText("Network failure")).toBeInTheDocument();
    });
  });

  it("shows empty state when no markets exist", async () => {
    vi.mocked(api.listMarkets).mockResolvedValue({ markets: [], count: 0, meta: mockMeta });
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByText(/No markets exist yet/)).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: /Create a market/ })).toHaveAttribute("href", "/markets/new");
  });

  it("renders charts and analytics data when data loads", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    });
    expect(screen.getByTestId("volume-chart")).toBeInTheDocument();
    expect(screen.getAllByText("ETH Price > $3000").length).toBeGreaterThan(0);
  });

  it("changes market selection via dropdown", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    });

    const select = screen.getByTestId("market-select");
    fireEvent.change(select, { target: { value: "m2" } });

    await waitFor(() => {
      expect((select as HTMLSelectElement).value).toBe("m2");
    });
  });

  it("toggles interval between Day and Hour", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    });

    const dayButton = screen.getByRole("button", { name: "Day" });
    const hourButton = screen.getByRole("button", { name: "Hour" });

    // Day should be active by default
    expect(dayButton).toHaveStyle({ borderColor: "var(--color-primary)" });

    fireEvent.click(hourButton);
    await waitFor(() => {
      expect(hourButton).toHaveStyle({ borderColor: "var(--color-primary)" });
    });

    fireEvent.click(dayButton);
    await waitFor(() => {
      expect(dayButton).toHaveStyle({ borderColor: "var(--color-primary)" });
    });
  });

  it("initializes from URL search params", async () => {
    renderWithProviders(<Analytics />, {
      initialEntries: ["/analytics?market=m2&interval=hour"],
    });

    await waitFor(() => {
      expect(screen.getByTestId("market-select")).toHaveValue("m2");
    });

    const hourButton = screen.getByRole("button", { name: "Hour" });
    expect(hourButton).toHaveStyle({ borderColor: "var(--color-primary)" });
  });

  it("shows AccountPnlSection prompt when no accountId is set", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    });
    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
  });
});
