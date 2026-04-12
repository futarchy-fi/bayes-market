import { test, expect } from "./fixtures/test-fixtures";

test.describe("Market Detail", () => {
  test("page loads and shows market title and description", async ({ page }) => {
    await page.goto("/markets/mkt-eth-above-5k");

    await expect(
      page.getByRole("heading", { name: "Will ETH trade above $5000 by December?" }),
    ).toBeVisible();
    await expect(
      page.getByText("Resolves YES if Ethereum trades above $5000"),
    ).toBeVisible();

    // Volume and liquidity info
    await expect(page.getByText("Volume:")).toBeVisible();
    await expect(page.getByText("Liquidity:")).toBeVisible();
  });

  test("probability bar displays outcomes with correct values", async ({ page }) => {
    await page.goto("/markets/mkt-eth-above-5k");

    // The probability bar legend should show outcome names and percentages
    // marginals: yes=0.42 (42.0%), no=0.58 (58.0%)
    await expect(page.getByText("Yes")).toBeVisible();
    await expect(page.getByText("No")).toBeVisible();
    await expect(page.getByText("42.0%")).toBeVisible();
    await expect(page.getByText("58.0%")).toBeVisible();
  });

  test("trading panel is visible with outcome selector and size input", async ({ page }) => {
    await page.goto("/markets/mkt-eth-above-5k");

    // Quick Trade panel should be visible for active market with session configured
    await expect(page.getByText("Quick Trade")).toBeVisible();
    await expect(page.getByLabel("Trade outcome")).toBeVisible();
    await expect(page.getByLabel("Position size")).toBeVisible();
    await expect(page.getByRole("button", { name: "Buy" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sell" })).toBeVisible();
  });

  test("position card shows when account has position in market", async ({ page }) => {
    await page.goto("/markets/mkt-eth-above-5k");

    // PositionCard should render with risk data for this market
    await expect(page.getByText("Your Position")).toBeVisible();
    await expect(page.getByText("Min Asset")).toBeVisible();
    await expect(page.getByText("450.25")).toBeVisible();
    await expect(page.getByText("Utilization")).toBeVisible();
  });

  test("P&L section renders for accounts with positions", async ({ page }) => {
    await page.goto("/markets/mkt-eth-above-5k");

    // PnLSummary should show P&L data
    await expect(page.getByText("Cost Basis").first()).toBeVisible();
  });
});
