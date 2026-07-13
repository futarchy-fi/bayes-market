import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MarketList from "@/routes/MarketList";
import { renderWithProviders } from "./helpers";

const mocks = vi.hoisted(() => ({
  useMarkets: vi.fn(),
  useInstruments: vi.fn(() => ({ data: [] })),
}));

vi.mock("@/lib/query/hooks", () => ({ useMarkets: mocks.useMarkets }));
vi.mock("@/lib/exchange/hooks", () => ({ useInstruments: mocks.useInstruments }));

const data = {
  markets: [{
    id: "m1",
    title: "Cached market",
    status: "active" as const,
    liquidity: 0,
    volume: 0,
    expires_at: "",
    marginals: { yes: 0.6 },
  }],
  count: 1,
  meta: { apiVersion: "test", timestamp: "2026-07-13T00:00:00Z" },
};

describe("MarketList reconnecting state", () => {
  it("keeps stale data with a reconnecting hint and only banners an error without data", () => {
    mocks.useMarkets.mockReturnValue({ data, isLoading: false, error: new Error("offline") });
    const first = renderWithProviders(<MarketList />);

    expect(screen.getByText("Cached market")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("reconnecting…");
    expect(screen.queryByText("offline")).not.toBeInTheDocument();

    first.unmount();
    mocks.useMarkets.mockReturnValue({ data: undefined, isLoading: false, error: new Error("offline") });
    renderWithProviders(<MarketList />);

    expect(screen.getByText("offline")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
