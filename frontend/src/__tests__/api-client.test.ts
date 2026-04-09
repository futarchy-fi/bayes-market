import { describe, it, expect, vi, beforeEach } from "vitest";
import { listMarkets, getMarket, getMarketPreview, getAccountRisk, BayesApiError } from "@/lib/api/client";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 400,
    status,
    json: () => Promise.resolve(data),
  };
}

describe("API Client", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("listMarkets calls /v1/markets", async () => {
    const body = { markets: [], count: 0, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await listMarkets();
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets", expect.objectContaining({ headers: {} }));
    expect(result.count).toBe(0);
  });

  it("listMarkets passes status filter", async () => {
    const body = { markets: [], count: 0, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await listMarkets("active");
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets?status=active", expect.any(Object));
  });

  it("getMarket calls /v1/markets/{id}", async () => {
    const body = { market: { id: "m1" }, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await getMarket("m1");
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1", expect.any(Object));
    expect(result.market.id).toBe("m1");
  });

  it("getAccountRisk calls /v1/accounts/{id}/risk", async () => {
    const body = { account: { id: "a1", risk: {} }, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await getAccountRisk("a1");
    expect(mockFetch).toHaveBeenCalledWith("/v1/accounts/a1/risk", expect.any(Object));
  });

  it("getMarketPreview calls /v1/markets/{id}/meta", async () => {
    const body = {
      preview: {
        marketId: "m1",
        title: "Market title",
        description: "Market description",
        url: "https://bayes.example/markets/m1",
        siteName: "Bayes Market",
        type: "website",
      },
      meta: { apiVersion: "1.0", timestamp: "" },
    };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await getMarketPreview("m1");
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/meta", expect.any(Object));
    expect(result.preview.marketId).toBe("m1");
  });

  it("throws BayesApiError on non-ok response", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ error: { code: "market_not_found", message: "Not found" }, meta: {} }, 404),
    );
    await expect(getMarket("bad")).rejects.toThrow(BayesApiError);
    try {
      await getMarket("bad");
    } catch (e) {
      expect((e as BayesApiError).code).toBe("market_not_found");
      expect((e as BayesApiError).status).toBe(404);
    }
  });
});
