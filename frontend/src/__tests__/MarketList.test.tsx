import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { MarketListFilterInput, MarketListResponse, MarketSummary } from "@/lib/api/types";
import { renderWithProviders } from "./helpers";
import MarketList from "@/routes/MarketList";
import * as api from "@/lib/api/client";

const mockClient = vi.hoisted(() => ({
  listMarkets: vi.fn(),
}));

vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return {
    ...actual,
    listMarkets: mockClient.listMarkets,
  };
});

const defaultMarkets: MarketSummary[] = [
  {
    id: "m1",
    title: "ETH Price > $3000",
    status: "active",
    liquidity: 150000,
    volume: 45000,
    expires_at: "2026-12-31T23:59:59Z",
  },
  {
    id: "m2",
    title: "Fed cuts rates before Q4",
    status: "closed",
    liquidity: 92000,
    volume: 18500,
    expires_at: "2026-09-30T23:59:59Z",
  },
];

const activeMarkets: MarketSummary[] = [
  defaultMarkets[0]!,
  {
    id: "m3",
    title: "Election turnout > 60%",
    status: "active",
    liquidity: 124000,
    volume: 31000,
    expires_at: "2026-11-03T23:59:59Z",
  },
];

const resolvedMarkets: MarketSummary[] = [
  {
    id: "m4",
    title: "BTC ETF Approval",
    status: "resolved",
    liquidity: 89000,
    volume: 23000,
    expires_at: "2026-03-14T23:59:59Z",
  },
  {
    id: "m5",
    title: "CPI prints below 3.0%",
    status: "resolved",
    liquidity: 76000,
    volume: 21000,
    expires_at: "2026-02-12T23:59:59Z",
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
      apiVersion: "1.0",
      timestamp: "2026-04-08T00:00:00Z",
      filters,
    },
  };
}

const defaultMarketsResponse = buildMarketListResponse(defaultMarkets, {
  status: null,
  include_resolved: false,
});

const activeMarketsResponse = buildMarketListResponse(activeMarkets, {
  status: "active",
  include_resolved: false,
});

const resolvedMarketsResponse = buildMarketListResponse(resolvedMarkets, {
  status: "resolved",
  include_resolved: true,
});

const emptyMarketsResponse = buildMarketListResponse([], {
  status: null,
  include_resolved: false,
});

function resolveMarketListResponse(filters?: MarketListFilterInput): MarketListResponse {
  const status = typeof filters === "string"
    ? filters
    : filters?.status;

  if (!status) {
    return defaultMarketsResponse;
  }

  if (status === "active") {
    return activeMarketsResponse;
  }

  if (status === "resolved") {
    return resolvedMarketsResponse;
  }

  throw new Error(`Unexpected market list filters: ${JSON.stringify(filters)}`);
}

describe("MarketList", () => {
  beforeEach(() => {
    vi.mocked(api.listMarkets).mockReset();
    vi.mocked(api.listMarkets).mockImplementation(async (filters?: MarketListFilterInput) => (
      resolveMarketListResponse(filters)
    ));
  });

  it("renders the markets heading", () => {
    renderWithProviders(<MarketList />);
    expect(screen.getByText("Markets")).toBeInTheDocument();
  });

  it("calls listMarkets(undefined) for the default all-status view and hides resolved rows", async () => {
    renderWithProviders(<MarketList />);

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenCalledWith(undefined);
      expect(screen.getByText("ETH Price > $3000")).toBeInTheDocument();
      expect(screen.getByText("Fed cuts rates before Q4")).toBeInTheDocument();
      expect(screen.queryByText("BTC ETF Approval")).not.toBeInTheDocument();
    });
  });

  it("requests and renders the active collection when the active filter is selected", async () => {
    renderWithProviders(<MarketList />);

    await screen.findByText("Fed cuts rates before Q4");

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "active" } });

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenLastCalledWith({ status: "active" });
      expect(screen.getByText("ETH Price > $3000")).toBeInTheDocument();
      expect(screen.getByText("Election turnout > 60%")).toBeInTheDocument();
      expect(screen.queryByText("Fed cuts rates before Q4")).not.toBeInTheDocument();
      expect(screen.queryByText("BTC ETF Approval")).not.toBeInTheDocument();
    });
  });

  it("requests and renders the resolved collection when the resolved filter is selected", async () => {
    renderWithProviders(<MarketList />);

    await screen.findByText("ETH Price > $3000");

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "resolved" } });

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenLastCalledWith({ status: "resolved" });
      expect(screen.getByText("BTC ETF Approval")).toBeInTheDocument();
      expect(screen.getByText("CPI prints below 3.0%")).toBeInTheDocument();
      expect(screen.queryByText("ETH Price > $3000")).not.toBeInTheDocument();
      expect(screen.queryByText("Fed cuts rates before Q4")).not.toBeInTheDocument();
    });
  });

  it("renders the status filter dropdown", () => {
    renderWithProviders(<MarketList />);
    expect(screen.getByRole("option", { name: "All statuses" })).toBeInTheDocument();
  });

  it("shows empty state when the default market request returns no rows", async () => {
    vi.mocked(api.listMarkets).mockImplementation(async (filters?: MarketListFilterInput) => (
      filters === undefined ? emptyMarketsResponse : resolveMarketListResponse(filters)
    ));

    renderWithProviders(<MarketList />);

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenCalledWith(undefined);
      expect(screen.getByText("No markets found.")).toBeInTheDocument();
    });
  });
});
