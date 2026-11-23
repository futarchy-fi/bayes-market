import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as paper from "@/lib/api/client";
import * as exchange from "@/lib/exchange/client";
import { filterMarketList, listMarkets, mapNetMarket } from "@/lib/dataSource";
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

  it("maps real volume and liquidity when provided on NetMarket", () => {
    const mapped = mapNetMarket({ ...netMarket, volume: 420.5, liquidity: 1500 });
    expect(mapped.volume).toBe(420.5);
    expect(mapped.liquidity).toBe(1500);
  });

  it("sorts accurately by volume, liquidity, probability (High->Low), and linked degree", () => {
    const response = {
      markets: [
        { id: "m1", title: "Low", status: "active" as const, volume: 10.5, liquidity: 50, expires_at: "", marginals: { yes: 0.2, no: 0.8 } },
        { id: "m2", title: "Mid", status: "active" as const, volume: 100.25, liquidity: 200, expires_at: "", marginals: { yes: 0.9, no: 0.1 } },
        { id: "m3", title: "High", status: "active" as const, volume: 25, liquidity: 500, expires_at: "", marginals: { yes: 0.55, no: 0.45 } },
      ],
      count: 3,
      meta: { apiVersion: "exchange", timestamp: "now" },
    };

    expect(filterMarketList(response, { sort: "volume" }).markets.map((m) => m.id)).toEqual(["m2", "m3", "m1"]);
    expect(filterMarketList(response, { sort: "liquidity" }).markets.map((m) => m.id)).toEqual(["m3", "m2", "m1"]);
    expect(filterMarketList(response, { sort: "probability" }).markets.map((m) => m.id)).toEqual(["m2", "m3", "m1"]);
    const linkCounts = new Map([["m1", 12], ["m2", 2], ["m3", 5]]);
    expect(filterMarketList(response, { sort: "linked" }, linkCounts).markets.map((m) => m.id)).toEqual(["m1", "m3", "m2"]);
  });
});
