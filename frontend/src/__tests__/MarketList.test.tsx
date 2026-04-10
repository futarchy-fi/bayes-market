import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
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

const mockMarkets = {
  markets: [
    { id: "m1", title: "ETH Price > $3000", status: "active" as const, liquidity: 150000, volume: 45000, expires_at: "2026-12-31T23:59:59Z" },
    { id: "m2", title: "BTC ETF Approval", status: "resolved" as const, liquidity: 89000, volume: 23000, expires_at: "2026-03-14T23:59:59Z" },
  ],
  count: 2,
  meta: {
    apiVersion: "1.0",
    timestamp: "2026-04-08T00:00:00Z",
    filters: { status: null, include_resolved: false },
  },
};

describe("MarketList", () => {
  beforeEach(() => {
    vi.mocked(api.listMarkets).mockReset();
    vi.mocked(api.listMarkets).mockResolvedValue(mockMarkets);
  });

  it("renders the markets heading", () => {
    renderWithProviders(<MarketList />);
    expect(screen.getByText("Markets")).toBeInTheDocument();
  });

  it("renders market cards after loading", async () => {
    renderWithProviders(<MarketList />);
    await waitFor(() => {
      expect(screen.getByText("ETH Price > $3000")).toBeInTheDocument();
    });
    expect(screen.getByText("BTC ETF Approval")).toBeInTheDocument();
  });

  it("uses default filters until a status is selected", async () => {
    renderWithProviders(<MarketList />);

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenCalledWith(undefined);
    });

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "active" } });
    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenLastCalledWith({ status: "active" });
    });

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "resolved" } });
    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenLastCalledWith({ status: "resolved" });
    });
  });

  it("shows status badges", async () => {
    renderWithProviders(<MarketList />);
    await waitFor(() => {
      expect(screen.getByText("active")).toBeInTheDocument();
    });
    expect(screen.getByText("resolved")).toBeInTheDocument();
  });

  it("renders the status filter dropdown", () => {
    renderWithProviders(<MarketList />);
    expect(screen.getByText("All statuses")).toBeInTheDocument();
  });

  it("shows empty state when no markets", async () => {
    vi.mocked(api.listMarkets).mockResolvedValue({ markets: [], count: 0, meta: mockMarkets.meta });
    renderWithProviders(<MarketList />);
    await waitFor(() => {
      expect(screen.getByText("No markets found.")).toBeInTheDocument();
    });
  });
});
