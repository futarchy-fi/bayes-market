import { test as base, type Page } from "@playwright/test";
import {
  ACCOUNT_ID,
  AGENT_ID,
  marketsResponse,
  marketDetailResponse,
  accountRiskResponse,
  accountExposureResponse,
  accountPnlResponse,
  marketPnlResponse,
  eventTradeSuccessResponse,
  marketEventsResponse,
  marketCommentsResponse,
  marketAnalyticsResponse,
  engineStatsResponse,
} from "./mock-data";

export interface TestOptions {
  accountId: string;
  agentId: string;
  setupSession: boolean;
}

export const test = base.extend<TestOptions>({
  accountId: [ACCOUNT_ID, { option: true }],
  agentId: [AGENT_ID, { option: true }],
  setupSession: [true, { option: true }],

  page: async ({ page, accountId, agentId, setupSession }, use) => {
    // Intercept all API routes with mock data
    await setupApiMocks(page);

    if (setupSession) {
      // Inject session into localStorage before navigating
      await page.addInitScript(
        ({ accountId, agentId }) => {
          localStorage.setItem(
            "bayes-session",
            JSON.stringify({ accountId, agentId }),
          );
        },
        { accountId, agentId },
      );
    }

    await use(page);
  },
});

async function setupApiMocks(page: Page) {
  // Market list
  await page.route("**/v1/markets?*", (route) => {
    const url = new URL(route.request().url());
    const q = url.searchParams.get("q")?.toLowerCase();
    const status = url.searchParams.get("status");
    const sort = url.searchParams.get("sort");

    let filtered = [...marketsResponse.markets];

    if (q) {
      filtered = filtered.filter((m) => m.title.toLowerCase().includes(q));
    }
    if (status) {
      filtered = filtered.filter((m) => m.status === status);
    }
    if (sort === "volume") {
      filtered.sort((a, b) => b.volume - a.volume);
    } else if (sort === "liquidity") {
      filtered.sort((a, b) => b.liquidity - a.liquidity);
    }

    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...marketsResponse,
        markets: filtered,
        count: filtered.length,
      }),
    });
  });

  // Market list (no query params) - must come after parameterized route
  await page.route("**/v1/markets", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(marketDetailResponse),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(marketsResponse),
    });
  });

  // Market detail
  await page.route("**/v1/markets/*/orders/event-trade", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(eventTradeSuccessResponse),
    });
  });

  await page.route("**/v1/markets/*/orders/probability-edit", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ meta: { apiVersion: "1.0.0", timestamp: new Date().toISOString() } }),
    });
  });

  await page.route("**/v1/markets/*/accounts/*/pnl", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(marketPnlResponse),
    });
  });

  await page.route("**/v1/markets/*/events*", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(marketEventsResponse),
    });
  });

  await page.route("**/v1/markets/*/comments*", (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          comment: {
            commentId: "cmt-001",
            marketId: marketDetailResponse.market.id,
            seq: 1,
            accountId: ACCOUNT_ID,
            body: "Test comment",
            createdAt: new Date().toISOString(),
          },
          meta: { apiVersion: "1.0.0", timestamp: new Date().toISOString() },
        }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(marketCommentsResponse),
    });
  });

  await page.route("**/v1/markets/*/engine-stats", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(engineStatsResponse),
    });
  });

  await page.route("**/v1/markets/*/analytics*", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(marketAnalyticsResponse),
    });
  });

  await page.route("**/v1/markets/*/meta", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        preview: {
          marketId: marketDetailResponse.market.id,
          title: marketDetailResponse.market.title,
          description: marketDetailResponse.market.description,
          url: "/markets/" + marketDetailResponse.market.id,
          siteName: "Bayes Market",
          type: "market",
        },
        meta: { apiVersion: "1.0.0", timestamp: new Date().toISOString() },
      }),
    });
  });

  await page.route("**/v1/markets/*/resolve", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        market: { ...marketDetailResponse.market, status: "resolved", resolution: "yes" },
        result: { terminal: true, status: "accepted", eventType: "CommandAccepted", eventId: "evt-r1", commandId: "cmd-r1", emittedAt: new Date().toISOString() },
        meta: { apiVersion: "1.0.0", timestamp: new Date().toISOString() },
      }),
    });
  });

  // Individual market detail (must come after more specific market/* routes)
  await page.route(/\/v1\/markets\/[^/]+$/, (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(marketDetailResponse),
    });
  });

  // Account endpoints
  await page.route("**/v1/accounts/*/risk", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(accountRiskResponse),
    });
  });

  await page.route("**/v1/accounts/*/exposure", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(accountExposureResponse),
    });
  });

  await page.route("**/v1/accounts/*/pnl", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(accountPnlResponse),
    });
  });

  // Health endpoint
  await page.route("**/health", (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        service: "bayes-market",
        status: "healthy",
        timestamp: new Date().toISOString(),
      }),
    });
  });

  // Service index
  await page.route(/^https?:\/\/[^/]+\/$/, (route) => {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        service: "bayes-market",
        status: "healthy",
        routes: {},
        meta: { apiVersion: "1.0.0", timestamp: new Date().toISOString() },
      }),
    });
  });

  // Block WebSocket connections (they should not cause test failures)
  await page.route("**/ws/**", (route) => route.abort());
}

export { expect } from "@playwright/test";
