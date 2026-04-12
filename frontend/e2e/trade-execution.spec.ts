import { test, expect } from "./fixtures/test-fixtures";

test.describe("Trade Execution", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/markets/mkt-eth-above-5k");
    await expect(page.getByText("Quick Trade")).toBeVisible();
  });

  test("select an outcome in the trading panel", async ({ page }) => {
    const outcomeSelect = page.getByLabel("Trade outcome");
    await outcomeSelect.selectOption("yes");

    // Selecting an outcome should show the current price
    await expect(page.getByText("Price: 42.0%")).toBeVisible();
  });

  test("enter a position size and see cost preview", async ({ page }) => {
    const outcomeSelect = page.getByLabel("Trade outcome");
    await outcomeSelect.selectOption("yes");

    const sizeInput = page.getByLabel("Position size");
    await sizeInput.fill("2");

    // The trade button should show the size
    await expect(
      page.getByRole("button", { name: /Buy yes \(2\)/ }),
    ).toBeVisible();
  });

  test("submit a trade and verify success confirmation", async ({ page }) => {
    // Select outcome
    await page.getByLabel("Trade outcome").selectOption("yes");
    // Set size
    await page.getByLabel("Position size").fill("2");
    // Click trade button
    await page.getByRole("button", { name: /Buy yes \(2\)/ }).click();

    // Verify success message with order ID
    await expect(page.getByText("Trade accepted - Order ord-new-001")).toBeVisible();

    // Verify receipt shows trade details
    await expect(page.getByText("buy").first()).toBeVisible();
    await expect(page.getByText("2.00").first()).toBeVisible();
  });

  test("verify trade receipt shows correct details", async ({ page }) => {
    await page.getByLabel("Trade outcome").selectOption("yes");
    await page.getByLabel("Position size").fill("2");
    await page.getByRole("button", { name: /Buy yes \(2\)/ }).click();

    // Wait for success
    await expect(page.getByText("Trade accepted")).toBeVisible();

    // Receipt should show side, outcome, size, price, notional
    // The receipt is a grid with labels and values
    const receipt = page.locator("text=Trade accepted").locator("..");
    await expect(receipt.getByText("Side")).toBeVisible();
    await expect(receipt.getByText("Outcome")).toBeVisible();
    await expect(receipt.getByText("Size")).toBeVisible();
    await expect(receipt.getByText("Price")).toBeVisible();
    await expect(receipt.getByText("Notional")).toBeVisible();
  });
});
