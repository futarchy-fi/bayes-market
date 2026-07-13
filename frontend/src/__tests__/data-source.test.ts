import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as paper from "@/lib/api/client";
import * as exchange from "@/lib/exchange/client";
import { listMarkets, mapNetMarket } from "@/lib/dataSource";
import { EXCHANGE_MODE_KEY } from "@/lib/exchangeMode";

vi.mock("@/lib/api/client", () => ({
  listMarkets: vi.fn(),
  getMarket: vi.fn(),
  getNetwork: vi.fn(),
  getGraphMarkets: vi.fn(),
}));

vi.mock("@/lib/exchange/client", () => ({
  getNetMarkets: vi.fn(),
  getNetMarket: vi.fn(),
  getNetMarginal: vi.fn(),
  getNetNetwork: vi.fn(),
  getNetGraphMarkets: vi.fn(),
}));

const netMarket: exchange.NetMarket = {
  id: "g1",
  variableId: "gcx_a",
  title: "Will compute get cheaper?",
  description: undefined,
  status: "open",
  outcomes: [{ id: "yes", name: "Yes" }, { id: "no", name: "No" }],
  marginals: { yes: 0.62, no: 0.38 },
  parents: [],
};

describe("market data source", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => localStorage.clear());

  it("routes list reads to the exchange when the flag is on", async () => {
    localStorage.setItem(EXCHANGE_MODE_KEY, "1");
    vi.mocked(exchange.getNetMarkets).mockResolvedValue({ markets: [netMarket], count: 1 });

    await listMarkets();

    expect(exchange.getNetMarkets).toHaveBeenCalledOnce();
    expect(paper.listMarkets).not.toHaveBeenCalled();
  });

  it("routes to the exchange by default (apex swap)", async () => {
    vi.mocked(exchange.getNetMarkets).mockResolvedValue({ markets: [netMarket], count: 1 });

    await listMarkets();

    expect(exchange.getNetMarkets).toHaveBeenCalledOnce();
    expect(paper.listMarkets).not.toHaveBeenCalled();
  });

  it("routes to the paper backend when opted out (?exchange=0)", async () => {
    localStorage.setItem(EXCHANGE_MODE_KEY, "0");
    const response = { markets: [], count: 0, meta: { apiVersion: "1", timestamp: "now" } };
    vi.mocked(paper.listMarkets).mockResolvedValue(response);

    await expect(listMarkets()).resolves.toBe(response);
    expect(exchange.getNetMarkets).not.toHaveBeenCalled();
  });

  it("maps a net market into the paper Market shape", () => {
    expect(mapNetMarket(netMarket)).toEqual({
      id: "g1",
      variableId: "gcx_a",
      title: "Will compute get cheaper?",
      description: "",
      status: "active",
      outcomes: netMarket.outcomes,
      marginals: netMarket.marginals,
      liquidity: 0,
      volume: 0,
      created_at: "",
      expires_at: "",
    });
  });
});
