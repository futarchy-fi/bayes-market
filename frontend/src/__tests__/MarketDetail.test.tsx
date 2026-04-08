import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import MarketDetail from "@/routes/MarketDetail";
import * as api from "@/lib/api/client";

vi.mock("@/lib/api/client");
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useParams: () => ({ marketId: "m1" }) };
});

const mockMarket = {
  market: {
    id: "m1",
    title: "ETH Price > $3000 on March 15",
    description: "Will ETH trade above $3000?",
    variableId: "eth_price_gt_3000_mar15",
    status: "active" as const,
    outcomes: [
      { id: "yes", name: "Yes" },
      { id: "no", name: "No" },
    ],
    marginals: { yes: 0.65, no: 0.35 },
    liquidity: 150000,
    volume: 45000,
    created_at: "2026-03-01T00:00:00Z",
    expires_at: "2026-12-31T23:59:59Z",
  },
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

const mockEvents = {
  events: [],
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

const mockEngineStats = {
  marketId: "m1",
  engine: { mode: "exact", backend: "junction-tree", version: "1.0", precision: "float64", compile_id: null, compile_type: null, source_state_hash: null },
  cliques: { num_cliques: 0, max_clique_size: 0, junction_tree_width: 0, cliques: [] },
  diagnostics: { request_count: 0, error_count: 0, inference: { p50_ms: 0, p95_ms: 0, p99_ms: 0, mean_ms: 0, sample_count: 0 }, cache: { hits: 0, misses: 0, hit_rate: 0 } },
  meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
};

describe("MarketDetail", () => {
  beforeEach(() => {
    vi.mocked(api.getMarket).mockResolvedValue(mockMarket);
    vi.mocked(api.getMarketEvents).mockResolvedValue(mockEvents);
    vi.mocked(api.getEngineStats).mockResolvedValue(mockEngineStats);
    vi.mocked(api.listMarkets).mockResolvedValue({
      markets: [{ id: "m1", title: "ETH Price > $3000 on March 15", status: "active" as const, liquidity: 150000, volume: 45000, expires_at: "2026-12-31T23:59:59Z" }],
      count: 1,
      meta: { apiVersion: "1.0", timestamp: "2026-04-08T00:00:00Z" },
    });
  });

  it("renders market title and description", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("ETH Price > $3000 on March 15");
    });
    expect(screen.getByText("Will ETH trade above $3000?")).toBeInTheDocument();
  });

  it("renders status badge", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("active")).toBeInTheDocument();
    });
  });

  it("renders outcome probabilities", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/Yes 65\.0%/)).toBeInTheDocument();
    });
    expect(screen.getByText(/No 35\.0%/)).toBeInTheDocument();
  });

  it("renders assumptions panel for active market", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/Variables & Assumptions/)).toBeInTheDocument();
    });
  });

  it("shows empty events state", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText("No events yet.")).toBeInTheDocument();
    });
  });

  it("renders junction tree panel", async () => {
    renderWithProviders(<MarketDetail />);
    await waitFor(() => {
      expect(screen.getByText(/Junction Tree & Inference/)).toBeInTheDocument();
    });
  });
});
