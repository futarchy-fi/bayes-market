import { test, expect } from "./fixtures/test-fixtures";

test.describe("Market List", () => {
  test("page loads and displays market cards", async ({ page }) => {
    await page.goto("/markets");

    await expect(page.getByRole("heading", { name: "Markets" })).toBeVisible();

    // All three market cards should be visible
    await expect(page.getByText("Will ETH trade above $5000 by December?")).toBeVisible();
    await expect(page.getByText("Will BTC reach $100K in 2026?")).toBeVisible();
    await expect(page.getByText("Solana mainnet launch on schedule?")).toBeVisible();

    // Stats line should show count
    await expect(page.getByText("3 markets")).toBeVisible();
  });

  test("search input filters markets by title", async ({ page }) => {
    await page.goto("/markets");
    await expect(page.getByText("3 markets")).toBeVisible();

    await page.getByPlaceholder("Search markets...").fill("ETH");

    // Only the ETH market should remain
    await expect(page.getByText("Will ETH trade above $5000 by December?")).toBeVisible();
    await expect(page.getByText("Will BTC reach $100K in 2026?")).not.toBeVisible();
    await expect(page.getByText("1 market")).toBeVisible();
  });

  test("sort dropdown changes market order", async ({ page }) => {
    await page.goto("/markets");
    await expect(page.getByText("3 markets")).toBeVisible();

    await page.getByLabel("Sort by").selectOption("volume");

    // After sort by volume, BTC (30K) should appear before ETH (12.5K)
    const cards = page.locator("a[href^='/markets/']");
    await expect(cards.first()).toContainText("BTC");
  });

  test("status filter shows only matching markets", async ({ page }) => {
    await page.goto("/markets");
    await expect(page.getByText("3 markets")).toBeVisible();

    await page.getByLabel("Filter by status").selectOption("resolved");

    // Only the resolved market should show
    await expect(page.getByText("Solana mainnet launch on schedule?")).toBeVisible();
    await expect(page.getByText("Will ETH trade above $5000 by December?")).not.toBeVisible();
    await expect(page.getByText("1 market")).toBeVisible();
  });

  test("clicking a market card navigates to /markets/:id", async ({ page }) => {
    await page.goto("/markets");

    await page.getByText("Will ETH trade above $5000 by December?").click();

    await expect(page).toHaveURL(/\/markets\/mkt-eth-above-5k/);
    await expect(page.getByRole("heading", { name: "Will ETH trade above $5000 by December?" })).toBeVisible();
  });
});
