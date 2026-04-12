import { test, expect } from "./fixtures/test-fixtures";
import { marketsResponse } from "./fixtures/mock-data";

test.describe("Portfolio", () => {
  test("page loads and shows risk metrics", async ({ page }) => {
    await page.goto("/portfolio");

    await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();

    // Risk metric cards: limit, available, utilization, health
    await expect(page.getByText("Limit")).toBeVisible();
    await expect(page.getByText("5000.00")).toBeVisible();
    await expect(page.getByText("Available")).toBeVisible();
    await expect(page.getByText("3749.50")).toBeVisible();
    await expect(page.getByText("Utilization")).toBeVisible();
    await expect(page.getByText("25.0%")).toBeVisible();
    await expect(page.getByText("Health")).toBeVisible();
    await expect(page.getByText("healthy")).toBeVisible();
  });

  test("positions table displays current positions", async ({ page }) => {
    await page.goto("/portfolio");

    await expect(page.getByText("Live Outcome Holdings")).toBeVisible();

    // Position from mock data: marketId=mkt-eth-above-5k, outcomeId=yes
    const marketTitle = marketsResponse.markets[0].title;
    await expect(page.getByRole("link", { name: marketTitle })).toBeVisible();
    await expect(page.getByText("yes").first()).toBeVisible();
  });

  test("account P&L summary renders", async ({ page }) => {
    await page.goto("/portfolio");

    // AccountPnL component should render P&L data
    // Check for P&L-related labels
    await expect(page.getByText("Cost Basis").first()).toBeVisible();
  });

  test("page handles empty portfolio gracefully", async ({ page }) => {
    // Override exposure to return empty positions
    await page.route("**/v1/accounts/*/exposure", (route) => {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          account: {
            id: "test-account-001",
            exposure: {
              maxPositionSize: 100,
              updatedAt: "2026-04-11T10:00:00Z",
              positions: [],
            },
          },
          meta: { apiVersion: "1.0.0", timestamp: "2026-04-12T00:00:00Z" },
        }),
      });
    });

    await page.goto("/portfolio");

    await expect(page.getByText("No live EventTrade positions.")).toBeVisible();
  });
});
