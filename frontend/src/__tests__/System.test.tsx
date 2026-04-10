import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import type { MarketListResponse, MarketSummary } from "@/lib/api/types";
import { renderWithProviders } from "./helpers";
import System from "@/routes/System";

const mockClient = vi.hoisted(() => ({
  getHealth: vi.fn(),
  getServiceIndex: vi.fn(),
  listMarkets: vi.fn(),
}));

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return {
    ...actual,
    ...mockClient,
  };
});

const mixedMarkets: MarketSummary[] = [
  {
    id: "m1",
    title: "Active Market",
    status: "active",
    liquidity: 1200,
    volume: 450,
    expires_at: "2026-12-31T00:00:00Z",
  },
  {
    id: "m2",
    title: "Resolved Market",
    status: "resolved",
    liquidity: 3000,
    volume: 1150,
    expires_at: "2026-10-31T00:00:00Z",
  },
];

function buildMarketListResponse(
  markets: MarketSummary[],
  filters: MarketListResponse["meta"]["filters"],
): MarketListResponse {
  return {
    markets,
    count: markets.length,
    meta: {
      apiVersion: "1.0.0",
      timestamp: "2026-04-08T12:00:00Z",
      filters,
    },
  };
}

const mixedMarketsResponse = buildMarketListResponse(mixedMarkets, {
  status: null,
  include_resolved: true,
});

function expectCountCard(section: HTMLElement, label: string, value: number | string) {
  const card = within(section).getByText(label).parentElement;
  expect(card).not.toBeNull();
  expect(within(card as HTMLElement).getByText(String(value))).toBeInTheDocument();
}

describe("System", () => {
  beforeEach(() => {
    mockClient.getHealth.mockReset();
    mockClient.getServiceIndex.mockReset();
    mockClient.listMarkets.mockReset();
    mockClient.getHealth.mockResolvedValue({
      service: "bayes-market",
      status: "ok",
      timestamp: "2026-04-08T12:00:00Z",
    });
    mockClient.getServiceIndex.mockResolvedValue({
      service: "bayes-market",
      status: "ok",
      routes: {
        health: ["/health"],
        markets: ["GET /v1/markets"],
      },
      meta: { apiVersion: "1.0.0", timestamp: "2026-04-08T12:00:00Z" },
    });
    mockClient.listMarkets.mockResolvedValue(mixedMarketsResponse);
  });

  it("renders system status heading", () => {
    renderWithProviders(<System />);
    expect(screen.getByText("System Status")).toBeInTheDocument();
  });

  it("shows API online after health check resolves", async () => {
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("API Online")).toBeInTheDocument();
    });
  });

  it("requests resolved-inclusive markets and shows market counts", async () => {
    renderWithProviders(<System />);

    await waitFor(() => {
      expect(mockClient.listMarkets).toHaveBeenCalledWith({ includeResolved: true });
    });

    const marketsSection = screen.getByRole("region", { name: "Markets" });

    await waitFor(() => {
      expectCountCard(marketsSection, "Total", 2);
      expectCountCard(marketsSection, "Active", 1);
      expectCountCard(marketsSection, "Resolved", 1);
      expectCountCard(marketsSection, "Closed", 0);
      expectCountCard(marketsSection, "Draft", 0);
    });
  });

  it("shows API surface routes", async () => {
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("GET /v1/markets")).toBeInTheDocument();
    });
  });

  it("shows platform aggregate stats", async () => {
    renderWithProviders(<System />);

    const platformStatsSection = await screen.findByRole("region", { name: "Platform Stats" });

    expectCountCard(platformStatsSection, "Total Volume", "1.6K");
    expectCountCard(platformStatsSection, "Total Liquidity", "4.2K");
    expectCountCard(platformStatsSection, "Active", 1);
    expectCountCard(platformStatsSection, "Resolved", 1);
  });
});
