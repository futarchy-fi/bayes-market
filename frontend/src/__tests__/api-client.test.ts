import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listMarkets,
  getMarket,
  getMarketPreview,
  getAccountRisk,
  getAccountExposure,
  submitEventTrade,
  BayesApiError,
} from "@/lib/api/client";
import type { AccountExposureResponse } from "@/lib/api/types";

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

  it("listMarkets defaults to /v1/markets", async () => {
    const body = {
      markets: [],
      count: 0,
      meta: {
        apiVersion: "1.0",
        timestamp: "",
        filters: { status: null, include_resolved: false },
      },
    };
    mockFetch.mockResolvedValue(jsonResponse(body));
    const result = await listMarkets();
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets", expect.objectContaining({ headers: {} }));
    expect(result.count).toBe(0);
  });

  it("listMarkets supports the legacy string status shorthand", async () => {
    const body = {
      markets: [],
      count: 0,
      meta: {
        apiVersion: "1.0",
        timestamp: "",
        filters: { status: "active", include_resolved: false },
      },
    };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await listMarkets("active");
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets?status=active", expect.any(Object));
  });

  it("listMarkets serializes object status filters", async () => {
    const body = {
      markets: [],
      count: 0,
      meta: {
        apiVersion: "1.0",
        timestamp: "",
        filters: { status: "active", include_resolved: false },
      },
    };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await listMarkets({ status: "active" });
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets?status=active", expect.any(Object));
  });

  it("listMarkets serializes includeResolved in snake_case", async () => {
    const body = {
      markets: [],
      count: 0,
      meta: {
        apiVersion: "1.0",
        timestamp: "",
        filters: { status: null, include_resolved: true },
      },
    };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await listMarkets({ includeResolved: true });
    expect(mockFetch).toHaveBeenCalledWith("/v1/markets?include_resolved=true", expect.any(Object));
  });

  it("listMarkets normalizes resolved filters to include resolved rows", async () => {
    const body = {
      markets: [],
      count: 0,
      meta: {
        apiVersion: "1.0",
        timestamp: "",
        filters: { status: "resolved", include_resolved: true },
      },
    };
    mockFetch.mockResolvedValue(jsonResponse(body));
    await listMarkets({ status: "resolved", includeResolved: false });
    expect(mockFetch).toHaveBeenCalledWith(
      "/v1/markets?status=resolved&include_resolved=true",
      expect.any(Object),
    );
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

  it("getAccountExposure calls /v1/accounts/{id}/exposure", async () => {
    const body = {
      account: {
        id: "a1",
        exposure: {
          maxPositionSize: 100,
          updatedAt: "2026-04-10T12:00:00Z",
          positions: [
            {
              marketId: "m1",
              outcomeId: "yes",
              netSize: 8.5,
              absSize: 8.5,
              lastTradePrice: 0.65,
              updatedAt: "2026-04-10T11:54:00Z",
              lastOrderId: "ord_1",
              lastCommandId: "cmd_1",
            },
          ],
        },
      },
      meta: {
        apiVersion: "1.0",
        timestamp: "2026-04-10T12:00:00Z",
      },
    } satisfies AccountExposureResponse;
    mockFetch.mockResolvedValue(jsonResponse(body));

    const result = await getAccountExposure("a1");

    expect(mockFetch).toHaveBeenCalledWith("/v1/accounts/a1/exposure", expect.any(Object));
    expect(result).toEqual(body);
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

  it("submitEventTrade posts the canonical size payload", async () => {
    const payload = {
      accountId: "acct_1",
      formula: [[{ variableId: "m1", outcomeId: "yes", negated: false }]],
      size: 12.5,
      side: "buy" as const,
      idempotencyKey: "idem_1",
    };
    const body = {
      order: {
        id: "ord_1",
        type: "EventTrade",
        marketId: "m1",
        accountId: "acct_1",
        commandId: "cmd_1",
        submittedAt: "2026-04-09T12:00:00Z",
        status: "filled",
        payload: {
          formula: payload.formula,
          size: payload.size,
          side: payload.side,
        },
        targetMarketId: "m1",
        targetOutcomeId: "yes",
        side: "buy",
        size: 12.5,
        price: 0.65,
        notional: 8.125,
        createdAt: "2026-04-09T12:00:00Z",
        filledAt: "2026-04-09T12:00:00Z",
        idempotencyKey: "idem_1",
      },
      result: {
        terminal: true,
        status: "accepted",
        eventType: "CommandAccepted",
        eventId: "evt_1",
        commandId: "cmd_1",
        emittedAt: "2026-04-09T12:00:00Z",
      },
      meta: {
        apiVersion: "1.0",
        timestamp: "",
        idempotencyKeyEcho: "idem_1",
      },
    };
    mockFetch.mockResolvedValue(jsonResponse(body, 201));

    const result = await submitEventTrade("m1", payload, {
      accountId: "acct_1",
      agentId: "agent_1",
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/v1/markets/m1/orders/event-trade",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(payload),
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-Bayes-Agent-Id": "agent_1",
        }),
      }),
    );
    expect(result.order.id).toBe("ord_1");
    expect(result.order.size).toBe(12.5);
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
