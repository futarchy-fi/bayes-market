import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "./helpers";
import System from "@/routes/System";

const mockClient = vi.hoisted(() => ({
  getHealth: vi.fn(),
  getServiceIndex: vi.fn(),
  listMarkets: vi.fn(),
}));

vi.mock("@/lib/api/client", () => mockClient);

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
      expect(screen.getByText("Active")).toBeInTheDocument();
    });
  });

  it("shows API surface routes", async () => {
    renderWithProviders(<System />);
    await waitFor(() => {
      expect(screen.getByText("GET /v1/markets")).toBeInTheDocument();
    });
  });
});
