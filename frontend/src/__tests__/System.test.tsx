import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import System from "@/routes/System";
import { EXCHANGE_MODE_KEY } from "@/lib/exchangeMode";

const mockClient = vi.hoisted(() => ({
  getHealth: vi.fn(),
  getServiceIndex: vi.fn(),
  listMarkets: vi.fn(),
}));

const mockExchange = vi.hoisted(() => ({
  getExchangeHealth: vi.fn(),
  getNetMarkets: vi.fn(),
}));

vi.mock("@/lib/api/client", () => mockClient);
vi.mock("@/lib/exchange/client", () => mockExchange);

describe("System", () => {
  beforeEach(() => {
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
    mockClient.listMarkets.mockResolvedValue({
      markets: [
        { id: "m1", title: "Test", status: "active", liquidity: 1000, volume: 500, expires_at: "2026-12-31T00:00:00Z" },
      ],
      count: 1,
      meta: { apiVersion: "1.0.0", timestamp: "2026-04-08T12:00:00Z" },
    });
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

  it("shows market counts", async () => {
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("Total")).toBeInTheDocument();
      expect(screen.getAllByText("Active").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows API surface routes", async () => {
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("GET /v1/markets")).toBeInTheDocument();
    });
  });

  it("shows platform aggregate stats", async () => {
    mockClient.listMarkets.mockResolvedValue({
      markets: [
        { id: "m1", title: "A", status: "active", liquidity: 1000, volume: 500, expires_at: "2026-12-31T00:00:00Z" },
        { id: "m2", title: "B", status: "resolved", liquidity: 2000, volume: 1500, expires_at: "2026-12-31T00:00:00Z" },
      ],
      count: 2,
      meta: { apiVersion: "1.0.0", timestamp: "2026-04-08T12:00:00Z" },
    });
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("Platform Stats")).toBeInTheDocument();
      expect(screen.getByText("Total Volume")).toBeInTheDocument();
      expect(screen.getByText("Total Liquidity")).toBeInTheDocument();
    });
  });

  // Step 1: Health loading state
  it("shows loading beacon and 'Checking...' while health is pending", () => {
    mockClient.getHealth.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<System />);
    expect(screen.getByText("Checking...")).toBeInTheDocument();
    const beacon = screen.getByText("Checking...").previousElementSibling as HTMLElement;
    expect(beacon).toHaveStyle({ background: "var(--color-warning, orange)" });
  });

  // Step 2: Health error state (Error instance)
  it("shows error message and red beacon when health rejects with Error", async () => {
    mockClient.getHealth.mockRejectedValue(new Error("Network error"));
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
    expect(screen.getByText("API Unreachable")).toBeInTheDocument();
    const beacon = screen.getByText("API Unreachable").previousElementSibling as HTMLElement;
    expect(beacon).toHaveStyle({ background: "var(--color-danger)" });
  });

  // Step 3: Health error state (non-Error fallback)
  it("shows 'Connection failed' when health rejects with non-Error", async () => {
    mockClient.getHealth.mockRejectedValue("string error");
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("Connection failed")).toBeInTheDocument();
    });
  });

  // Step 4: Healthy beacon style (green + glow)
  it("shows green beacon with glow when health returns ok", async () => {
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("API Online")).toBeInTheDocument();
    });
    const beacon = screen.getByText("API Online").previousElementSibling as HTMLElement;
    expect(beacon).toHaveStyle({ background: "var(--color-success)" });
    expect(beacon).toHaveStyle({ boxShadow: "0 0 8px var(--color-success)" });
  });

  // Step 5: Markets loading state
  it("shows loading indicator when markets are pending", () => {
    mockClient.listMarkets.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<System />);
    expect(screen.getByText("Markets")).toBeInTheDocument();
    // LoadingPage renders a spinner container; the Platform Stats section should not appear
    expect(screen.queryByText("Platform Stats")).not.toBeInTheDocument();
  });

  // Step 6: Platform stats formatCurrency integration
  it("renders formatted currency values for platform stats", async () => {
    mockClient.listMarkets.mockResolvedValue({
      markets: [
        { id: "m1", title: "A", status: "active", liquidity: 1000, volume: 500, expires_at: "2026-12-31T00:00:00Z" },
        { id: "m2", title: "B", status: "active", liquidity: 2000, volume: 1500, expires_at: "2026-12-31T00:00:00Z" },
      ],
      count: 2,
      meta: { apiVersion: "1.0.0", timestamp: "2026-04-08T12:00:00Z" },
    });
    renderWithProviders(<System />);
    await waitFor(() => {
      // 500 + 1500 = 2000 → formatCurrency(2000) = "2.0K"
      expect(screen.getByText("2.0K")).toBeInTheDocument();
      // 1000 + 2000 = 3000 → formatCurrency(3000) = "3.0K"
      expect(screen.getByText("3.0K")).toBeInTheDocument();
    });
  });

  // Step 7: CountCard color assertion & no duplicate Active/Resolved cards
  it("applies correct color to active markets count card and avoids duplicating Active/Resolved in Platform Stats", async () => {
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("Platform Stats")).toBeInTheDocument();
    });
    const platformStats = screen.getByText("Platform Stats").closest("div")!;
    expect(platformStats.textContent).not.toContain("Active");
    expect(platformStats.textContent).not.toContain("Resolved");

    const marketsSection = screen.getByText("Markets").closest("div")!;
    let activeValueEl: HTMLElement | null = null;
    marketsSection.querySelectorAll("div").forEach((div) => {
      if (div.textContent === "Active" && div.previousElementSibling) {
        activeValueEl = div.previousElementSibling as HTMLElement;
      }
    });
    expect(activeValueEl).not.toBeNull();
    expect(activeValueEl!).toHaveStyle({ color: "var(--color-success)" });
  });

  it("checks exchange health (/v1/health) and displays credits totals in exchange mode", async () => {
    window.localStorage.removeItem(EXCHANGE_MODE_KEY);
    mockExchange.getExchangeHealth.mockResolvedValue({
      status: "ok",
      users: 17,
      net: { markets: 909, orders: 2004, enabled: true },
    });
    mockExchange.getNetMarkets.mockResolvedValue({
      markets: [
        {
          id: "f1",
          variableId: "ftm_agi_by_2035",
          title: "AGI 2035",
          status: "open",
          outcomes: [{ id: "yes", name: "Yes" }, { id: "no", name: "No" }],
          marginals: { yes: 0.3, no: 0.7 },
          parents: [],
          volume: 1200,
          liquidity: 5000,
        },
      ],
      count: 1,
    });

    renderWithProviders(<System />);

    await waitFor(() => {
      expect(screen.getByText("API Online")).toBeInTheDocument();
      expect(screen.getByText("1.2K credits")).toBeInTheDocument();
      expect(screen.getByText("5.0K credits")).toBeInTheDocument();
    });
    expect(mockExchange.getExchangeHealth).toHaveBeenCalled();
    expect(screen.getByText("2,004")).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();
  });

  // Step 8: Empty markets array
  it("renders zero counts and zero totals for empty markets array", async () => {
    mockClient.listMarkets.mockResolvedValue({
      markets: [],
      count: 0,
      meta: { apiVersion: "1.0.0", timestamp: "2026-04-08T12:00:00Z" },
    });
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("Markets")).toBeInTheDocument();
      // All status counts should be 0
      const zeros = screen.getAllByText("0");
      expect(zeros.length).toBeGreaterThanOrEqual(5); // Total, Active, Resolved, Closed, Draft
    });
    // Platform Stats section should show formatted zero values
    await waitFor(() => {
      expect(screen.getByText("Platform Stats")).toBeInTheDocument();
      // formatCurrency(0) = "0.00"
      const zeroValues = screen.getAllByText("0.00");
      expect(zeroValues.length).toBeGreaterThanOrEqual(2); // Total Volume and Total Liquidity
    });
  });

  // Step 9: API info section
  it("renders API version and route groups from service index", async () => {
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("API Surface")).toBeInTheDocument();
      expect(screen.getByText("Version: 1.0.0")).toBeInTheDocument();
      // Route groups
      expect(screen.getByText("health")).toBeInTheDocument();
      expect(screen.getByText("markets")).toBeInTheDocument();
      // Individual routes
      expect(screen.getByText("/health")).toBeInTheDocument();
      expect(screen.getByText("GET /v1/markets")).toBeInTheDocument();
    });
  });
});
