import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listMarkets,
  getMarket,
  getMarketAnalytics,
  getMarketPreview,
  getAccountRisk,
  getAccountPnl,
  createMarket,
  getMarketEvents,
  getMarketComments,
  getEngineStats,
  submitProbabilityEdit,
  resolveMarket,
  getHealth,
  getServiceIndex,
  submitEventTrade,
  submitMarketComment,
  BayesApiError,
} from "@/lib/api/client";

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
    await listMarkets({ status: "active" });
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets?status=active", expect.any(Object));
  });

  it("listMarkets passes normalized sort and search filters", async () => {
    const body = { markets: [], count: 0, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await listMarkets({ status: "all", sort: "volume", q: "  ETH  " });
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets?sort=volume&q=ETH", expect.any(Object));
  });

  it("listMarkets omits blank search values", async () => {
    const body = { markets: [], count: 0, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await listMarkets({ q: "   ", sort: "created" });
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets?sort=created", expect.any(Object));
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

  it("getMarketAnalytics calls /v1/markets/{id}/analytics", async () => {
    const body = { marketId: "m1", summary: {}, priceSeries: [], volumeBuckets: [], topTraders: [], meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await getMarketAnalytics("m1");
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/analytics", expect.any(Object));
  });

  it("getMarketAnalytics passes interval filter", async () => {
    const body = { marketId: "m1", summary: {}, priceSeries: [], volumeBuckets: [], topTraders: [], meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await getMarketAnalytics("m1", { interval: "day" });
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/analytics?interval=day", expect.any(Object));
  });

  it("getAccountPnl calls /v1/accounts/{id}/pnl", async () => {
    const body = { account: { id: "a1", pnl: {} }, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await getAccountPnl("a1");
    expect(mockFetch).toHaveBeenCalledWith("/v1/accounts/a1/pnl", expect.any(Object));
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

  // --- Step 2: Simple GET functions ---

  it("getEngineStats calls /v1/markets/{id}/engine-stats", async () => {
    const body = { marketId: "m1", stats: {}, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await getEngineStats("m1");
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/engine-stats", expect.any(Object));
    expect(result.marketId).toBe("m1");
  });

  it("getHealth calls /health", async () => {
    const body = { service: "bayes-market", status: "ok", timestamp: "2024-01-01T00:00:00Z" };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await getHealth();
    expect(mockFetch).toHaveBeenCalledWith("/health", expect.any(Object));
    expect(result.status).toBe("ok");
  });

  it("getServiceIndex calls /", async () => {
    const body = { service: "bayes-market", status: "ok", routes: {}, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await getServiceIndex();
    expect(mockFetch).toHaveBeenCalledWith("/", expect.any(Object));
    expect(result.service).toBe("bayes-market");
  });

  // --- Step 3: Paginated GET functions ---

  it("getMarketEvents calls /v1/markets/{id}/events with no params", async () => {
    const body = { events: [], meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await getMarketEvents("m1");
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/events", expect.any(Object));
  });

  it("getMarketEvents passes fromSeq and limit params", async () => {
    const body = { events: [], meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await getMarketEvents("m1", { fromSeq: 5, limit: 10 });
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/events?fromSeq=5&limit=10", expect.any(Object));
  });

  it("getMarketComments calls /v1/markets/{id}/comments with no params", async () => {
    const body = { comments: [], meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await getMarketComments("m1");
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/comments", expect.any(Object));
  });

  it("getMarketComments passes fromSeq and limit params", async () => {
    const body = { comments: [], meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await getMarketComments("m1", { fromSeq: 0, limit: 20 });
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/comments?fromSeq=0&limit=20", expect.any(Object));
  });

  // --- Step 4: createMarket POST with optional session ---

  it("createMarket posts to /v1/markets without session", async () => {
    const payload = { title: "Test", description: "A test market", outcomes: [{ id: "yes", name: "Yes" }], expires_at: "2025-01-01T00:00:00Z" };
    const body = { market: { id: "m-new" }, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await createMarket(payload);
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets", expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }));
    const headers = mockFetch.mock.calls[0]![1].headers;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Bayes-Agent-Id"]).toBeUndefined();
    expect(result.market.id).toBe("m-new");
  });

  it("createMarket posts to /v1/markets with session sets X-Bayes-Agent-Id", async () => {
    const payload = { title: "Test", description: "A test market", outcomes: [{ id: "yes", name: "Yes" }], expires_at: "2025-01-01T00:00:00Z" };
    const session = { accountId: "acc1", agentId: "agent-42" };
    const body = { market: { id: "m-new" }, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await createMarket(payload, session);
    const headers = mockFetch.mock.calls[0]![1].headers;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Bayes-Agent-Id"]).toBe("agent-42");
  });

  // --- Step 5: POST functions with required session ---

  it("submitProbabilityEdit posts to /v1/markets/{id}/orders/probability-edit", async () => {
    const payload = {
      accountId: "acc1",
      variableId: "v1",
      target: { kind: "marginal" as const, outcomeId: "yes", probability: 0.7 },
      context: [],
    };
    const session = { accountId: "acc1", agentId: "agent-1" };
    const body = { command: {}, order: { orderId: "o1", commandId: "c1", marketId: "m1", type: "prob-edit" }, assetDelta: {}, terminalOutcome: {}, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await submitProbabilityEdit("m1", payload, session);
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/orders/probability-edit", expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }));
    const headers = mockFetch.mock.calls[0]![1].headers;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Bayes-Agent-Id"]).toBe("agent-1");
    expect(result.order.orderId).toBe("o1");
  });

  it("resolveMarket posts to /v1/markets/{id}/resolve", async () => {
    const payload = { accountId: "acc1", outcomeId: "yes" };
    const session = { accountId: "acc1", agentId: "agent-2" };
    const body = { market: { id: "m1" }, result: { terminal: true, status: "resolved", eventType: "resolve", eventId: "e1", commandId: "c1", emittedAt: "" }, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await resolveMarket("m1", payload, session);
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/resolve", expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }));
    const headers = mockFetch.mock.calls[0]![1].headers;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Bayes-Agent-Id"]).toBe("agent-2");
    expect(result.result.terminal).toBe(true);
  });

  it("submitEventTrade posts to /v1/markets/{id}/orders/event-trade", async () => {
    const payload = {
      accountId: "acc1",
      formula: [[{ variableId: "v1", outcomeId: "yes", negated: false }]],
      side: "buy" as const,
    };
    const session = { accountId: "acc1", agentId: "agent-3" };
    const body = { command: {}, order: { orderId: "o2", commandId: "c2", marketId: "m1", type: "event-trade" }, assetDelta: {}, terminalOutcome: {}, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await submitEventTrade("m1", payload, session);
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/orders/event-trade", expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }));
    const headers = mockFetch.mock.calls[0]![1].headers;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Bayes-Agent-Id"]).toBe("agent-3");
    expect(result.order.orderId).toBe("o2");
  });

  it("submitMarketComment posts to /v1/markets/{id}/comments", async () => {
    const payload = { accountId: "acc1", body: "Great market!" };
    const session = { accountId: "acc1", agentId: "agent-4" };
    const body = { comment: { commentId: "c1", marketId: "m1", seq: 1, accountId: "acc1", body: "Great market!", createdAt: "" }, meta: { apiVersion: "1.0", timestamp: "" } };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await submitMarketComment("m1", payload, session);
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets/m1/comments", expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }));
    const headers = mockFetch.mock.calls[0]![1].headers;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Bayes-Agent-Id"]).toBe("agent-4");
    expect(result.comment.commentId).toBe("c1");
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
