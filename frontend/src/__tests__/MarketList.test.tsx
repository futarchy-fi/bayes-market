import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import MarketList from "@/routes/MarketList";
import * as api from "@/lib/api/client";

vi.mock("@/lib/api/client");

const mockMarkets = {
  markets: [
    { id: "m1", title: "ETH Price > $3000", status: "active" as const, liquidity: 150000, volume: 45000, expires_at: "2026-12-31T23:59:59Z" },
    { id: "m2", title: "BTC ETF Approval", status: "resolved" as const, liquidity: 89000, volume: 23000, expires_at: "2026-03-14T23:59:59Z" },
  ],
  count: 2,
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

describe("MarketList", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.mocked(api.listMarkets).mockResolvedValue(mockMarkets);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the markets heading and filters", () => {
    renderWithProviders(<MarketList />);
    expect(screen.getByText("Markets")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Sort" })).toBeInTheDocument();
  });

  it("renders market cards after loading", async () => {
    renderWithProviders(<MarketList />);
    await waitFor(() => {
      expect(screen.getByText("ETH Price > $3000")).toBeInTheDocument();
    });
    expect(screen.getByText("BTC ETF Approval")).toBeInTheDocument();
  });

  it("shows status badges", async () => {
    renderWithProviders(<MarketList />);
    await waitFor(() => {
      expect(screen.getAllByText("active").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("resolved").length).toBeGreaterThan(0);
  });

  it("hydrates filter controls from the URL and normalizes search", async () => {
    renderWithProviders(<MarketList />, {
      route: "/markets?status=resolved&sort=liquidity&q=%20BTC%20",
    });

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenCalledWith({
        status: "resolved",
        sort: "liquidity",
        q: "BTC",
      });
    });

    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("BTC");
    expect(screen.getByRole("combobox", { name: "Status" })).toHaveValue("resolved");
    expect(screen.getByRole("combobox", { name: "Sort" })).toHaveValue("liquidity");
  });

  it("refetches when status and sort filters change", async () => {
    renderWithProviders(<MarketList />);

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenCalledWith({});
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), {
      target: { value: "active" },
    });

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenLastCalledWith({ status: "active" });
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Sort" }), {
      target: { value: "volume" },
    });

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenLastCalledWith({
        status: "active",
        sort: "volume",
      });
    });
  });

  it("debounces and trims search before refetching", async () => {
    renderWithProviders(<MarketList />);

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenCalledWith({});
    });

    vi.mocked(api.listMarkets).mockClear();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
      target: { value: "  ETH  " },
    });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, SEARCH_DEBOUNCE_MS - 50));
    });
    expect(api.listMarkets).not.toHaveBeenCalled();

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 75));
    });

    await waitFor(() => {
      expect(api.listMarkets).toHaveBeenCalledWith({ q: "ETH" });
    });
  });

  it("shows empty state when no markets", async () => {
    vi.mocked(api.listMarkets).mockResolvedValue({ markets: [], count: 0, meta: mockMarkets.meta });
    renderWithProviders(<MarketList />);
    await waitFor(() => {
      expect(screen.getByText("No markets found.")).toBeInTheDocument();
    });
  });
});

const SEARCH_DEBOUNCE_MS = 300;
