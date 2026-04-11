import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders, createMockQueryResult } from "./helpers";
import Portfolio from "@/routes/Portfolio";

// ---------------------------------------------------------------------------
// Mocks — hook-level, following codebase conventions
// ---------------------------------------------------------------------------

vi.mock("@/features/session/context", async () => {
  const actual = await vi.importActual<typeof import("@/features/session/context")>(
    "@/features/session/context",
  );
  return {
    ...actual,
    useSession: vi.fn(),
  };
});

vi.mock("@/lib/query/hooks", () => ({
  useAccountRisk: vi.fn(),
  useMarkets: vi.fn(),
}));

import { useSession } from "@/features/session/context";
import { useAccountRisk, useMarkets } from "@/lib/query/hooks";

const mockUseSession = vi.mocked(useSession);
const mockUseAccountRisk = vi.mocked(useAccountRisk);
const mockUseMarkets = vi.mocked(useMarkets);

// ---------------------------------------------------------------------------
// Shared fixtures
// ---------------------------------------------------------------------------

const unconfiguredSession = {
  session: { accountId: "", agentId: "" },
  setAccountId: vi.fn(),
  setAgentId: vi.fn(),
  isConfigured: false,
};

const configuredSession = {
  session: { accountId: "acc-123", agentId: "agent-1" },
  setAccountId: vi.fn(),
  setAgentId: vi.fn(),
  isConfigured: true,
};


function makeRiskData(overrides: {
  status?: "healthy" | "warning" | "critical";
  markets?: Array<{
    marketId: string;
    minAsset: number;
    capacityConsumed: number;
    utilization: number;
    commandCount: number;
    lastOrderId: string;
    lastCommandId: string;
    updatedAt: string;
  }>;
  updatedAt?: string;
} = {}) {
  return {
    account: {
      id: "acc-123",
      risk: {
        minAssets: {
          overall: 42.5,
          markets: overrides.markets ?? [],
        },
        capacityIndicators: {
          limit: 1000.0,
          available: 750.25,
          consumed: 249.75,
          utilization: 0.24975,
          status: overrides.status ?? "healthy",
        },
        updatedAt: overrides.updatedAt ?? "2026-04-09T12:30:00Z",
      },
    },
    meta: { apiVersion: "1.0", timestamp: "2026-04-09T12:30:00Z" },
  };
}

const defaultMarkets = {
  markets: [] as Array<{ id: string; title: string; status: string; liquidity: number; volume: number; expires_at: string }>,
  count: 0,
  meta: { apiVersion: "1.0", timestamp: "2026-04-09T00:00:00Z" },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Portfolio", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMarkets.mockReturnValue(createMockQueryResult({ data: defaultMarkets }) as ReturnType<typeof useMarkets>);
  });

  // -------------------------------------------------------------------------
  // Step 1 — Unconfigured session
  // -------------------------------------------------------------------------
  it("renders account prompt when no session configured", () => {
    mockUseSession.mockReturnValue(unconfiguredSession);
    mockUseAccountRisk.mockReturnValue(createMockQueryResult() as ReturnType<typeof useAccountRisk>);

    renderWithProviders(<Portfolio />);
    expect(screen.getByText(/Set your Account ID/)).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Step 2 — Loading state
  // -------------------------------------------------------------------------
  it("renders loading page while risk data loads", () => {
    mockUseSession.mockReturnValue(configuredSession);
    mockUseAccountRisk.mockReturnValue(createMockQueryResult({ isLoading: true }) as ReturnType<typeof useAccountRisk>);

    const { container } = renderWithProviders(<Portfolio />);
    // LoadingPage renders an SVG spinner
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Step 3 — Error state
  // -------------------------------------------------------------------------
  it("renders error message when risk fetch fails", () => {
    mockUseSession.mockReturnValue(configuredSession);
    mockUseAccountRisk.mockReturnValue(createMockQueryResult({ error: new Error("fail") }) as ReturnType<typeof useAccountRisk>);

    renderWithProviders(<Portfolio />);
    expect(screen.getByText("Account not found or no positions yet.")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Step 4 — Full data rendering (MetricCards)
  // -------------------------------------------------------------------------
  it("renders portfolio heading and metric cards with full data", () => {
    mockUseSession.mockReturnValue(configuredSession);
    mockUseAccountRisk.mockReturnValue(createMockQueryResult({ data: makeRiskData(), isSuccess: true }) as ReturnType<typeof useAccountRisk>);

    renderWithProviders(<Portfolio />);

    expect(screen.getByText("Portfolio")).toBeInTheDocument();
    expect(screen.getByText("1000.00")).toBeInTheDocument(); // Limit
    expect(screen.getByText("750.25")).toBeInTheDocument(); // Available
    expect(screen.getByText("249.75")).toBeInTheDocument(); // Consumed
    expect(screen.getByText("25.0%")).toBeInTheDocument(); // Utilization
    expect(screen.getByText("healthy")).toBeInTheDocument(); // Health
    expect(screen.getByText("42.50")).toBeInTheDocument(); // Min Asset (Overall)
  });

  // -------------------------------------------------------------------------
  // Step 5 — Health status colors
  // -------------------------------------------------------------------------
  it.each([
    { status: "healthy" as const, color: "var(--color-success)" },
    { status: "warning" as const, color: "var(--color-warning)" },
    { status: "critical" as const, color: "var(--color-danger)" },
  ])("renders health status '$status' with correct color", ({ status, color }) => {
    mockUseSession.mockReturnValue(configuredSession);
    mockUseAccountRisk.mockReturnValue(createMockQueryResult({ data: makeRiskData({ status }), isSuccess: true }) as ReturnType<typeof useAccountRisk>);

    renderWithProviders(<Portfolio />);

    const healthValue = screen.getByText(status);
    expect(healthValue).toHaveStyle({ color });
  });

  // -------------------------------------------------------------------------
  // Step 6 — Timestamp display
  // -------------------------------------------------------------------------
  it("renders last-updated timestamp", () => {
    const knownTimestamp = "2026-04-09T12:30:00Z";
    mockUseSession.mockReturnValue(configuredSession);
    mockUseAccountRisk.mockReturnValue(createMockQueryResult({ data: makeRiskData({ updatedAt: knownTimestamp }), isSuccess: true }) as ReturnType<typeof useAccountRisk>);

    renderWithProviders(<Portfolio />);

    const expected = new Date(knownTimestamp).toLocaleString();
    expect(screen.getByText(`Last updated: ${expected}`)).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Step 7 — Per-market positions table
  // -------------------------------------------------------------------------
  it("renders per-market positions table with market links", () => {
    const marketRows = [
      {
        marketId: "mkt-1",
        minAsset: 15.5,
        capacityConsumed: 50,
        utilization: 0.123,
        commandCount: 7,
        lastOrderId: "ord-1",
        lastCommandId: "cmd-1",
        updatedAt: "2026-04-09T12:00:00Z",
      },
      {
        marketId: "mkt-2",
        minAsset: 27.0,
        capacityConsumed: 80,
        utilization: 0.456,
        commandCount: 3,
        lastOrderId: "ord-2",
        lastCommandId: "cmd-2",
        updatedAt: "2026-04-09T12:00:00Z",
      },
    ];

    mockUseSession.mockReturnValue(configuredSession);
    mockUseAccountRisk.mockReturnValue(createMockQueryResult({ data: makeRiskData({ markets: marketRows }), isSuccess: true }) as ReturnType<typeof useAccountRisk>);
    mockUseMarkets.mockReturnValue(createMockQueryResult({
      data: {
        markets: [
          { id: "mkt-1", title: "ETH Price > $3000", status: "active", liquidity: 100, volume: 200, expires_at: "2026-12-31T00:00:00Z" },
          { id: "mkt-2", title: "BTC Price > $100k", status: "active", liquidity: 500, volume: 1000, expires_at: "2026-12-31T00:00:00Z" },
        ],
        count: 2,
        meta: { apiVersion: "1.0", timestamp: "2026-04-09T00:00:00Z" },
      },
    }) as ReturnType<typeof useMarkets>);

    renderWithProviders(<Portfolio />);

    // Table headers
    expect(screen.getByRole("columnheader", { name: "Market" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Min Asset" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Utilization" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Trades" })).toBeInTheDocument();

    // Market links with titles
    const ethLink = screen.getByText("ETH Price > $3000");
    expect(ethLink.closest("a")).toHaveAttribute("href", "/markets/mkt-1");

    const btcLink = screen.getByText("BTC Price > $100k");
    expect(btcLink.closest("a")).toHaveAttribute("href", "/markets/mkt-2");

    // Numeric values
    expect(screen.getByText("15.50")).toBeInTheDocument();
    expect(screen.getByText("27.00")).toBeInTheDocument();
    expect(screen.getByText("12.3%")).toBeInTheDocument();
    expect(screen.getByText("45.6%")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Step 8 — Empty positions
  // -------------------------------------------------------------------------
  it("renders 'No positions.' when markets array is empty", () => {
    mockUseSession.mockReturnValue(configuredSession);
    mockUseAccountRisk.mockReturnValue(createMockQueryResult({ data: makeRiskData({ markets: [] }), isSuccess: true }) as ReturnType<typeof useAccountRisk>);

    renderWithProviders(<Portfolio />);
    expect(screen.getByText("No positions.")).toBeInTheDocument();
  });
});
