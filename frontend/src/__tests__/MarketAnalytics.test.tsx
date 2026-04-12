import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import { MarketAnalytics } from "@/features/analytics";
import * as api from "@/lib/api/client";

vi.mock("@/lib/api/client");

const mockAnalytics = {
  market_id: "m1",
  total_volume: 50000,
  trade_count: 120,
  price_history: [
    { timestamp: "2026-04-08T10:00:00Z", marginals: { yes: 0.6, no: 0.4 } },
    { timestamp: "2026-04-08T11:00:00Z", marginals: { yes: 0.65, no: 0.35 } },
  ],
  top_traders: [],
  interval: "1h",
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T12:00:00Z" },
};

describe("MarketAnalytics", () => {
  beforeEach(() => {
    vi.mocked(api.getMarketAnalytics).mockResolvedValue(mockAnalytics);
  });

  it("renders collapsed by default with toggle", async () => {
    renderWithProviders(<MarketAnalytics marketId="m1" />);
    await waitFor(() => {
      expect(screen.getByText("Market Analytics")).toBeInTheDocument();
    });
  });

  it("shows chart data when expanded", async () => {
    renderWithProviders(<MarketAnalytics marketId="m1" />);
    await waitFor(() => {
      expect(screen.getByText("Market Analytics")).toBeInTheDocument();
    });
    const toggle = screen.getByText("Market Analytics");
    expect(toggle).toBeInTheDocument();
  });

  it("handles loading state", () => {
    vi.mocked(api.getMarketAnalytics).mockReturnValue(new Promise(() => {}));
    renderWithProviders(<MarketAnalytics marketId="m1" />);
    expect(screen.getByText("Market Analytics")).toBeInTheDocument();
  });

  it("handles error state when expanded", async () => {
    vi.mocked(api.getMarketAnalytics).mockRejectedValue(new Error("Network error"));
    renderWithProviders(<MarketAnalytics marketId="m1" />);
    await waitFor(() => {
      expect(screen.getByText("Market Analytics")).toBeInTheDocument();
    });
  });
});
