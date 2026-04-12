import { test, expect } from "./fixtures/test-fixtures";

test.describe("Session & Navigation", () => {
  test("entering Account ID in header input persists to localStorage", async ({ page }) => {
    // Start without a session
    test.use({ setupSession: false });

    await page.goto("/markets");

    const accountInput = page.getByPlaceholder("Account ID");
    await accountInput.fill("my-custom-account");

    // Verify it persisted to localStorage
    const stored = await page.evaluate(() => localStorage.getItem("bayes-session"));
    const session = JSON.parse(stored!);
    expect(session.accountId).toBe("my-custom-account");
  });

  test("navigation links work correctly", async ({ page }) => {
    await page.goto("/markets");

    // Click Portfolio link
    await page.getByRole("link", { name: "Portfolio" }).click();
    await expect(page).toHaveURL(/\/portfolio/);
    await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();

    // Click Markets link to go back
    await page.getByRole("link", { name: "Markets" }).click();
    await expect(page).toHaveURL(/\/markets/);
    await expect(page.getByRole("heading", { name: "Markets" })).toBeVisible();
  });

  test("page without session shows appropriate state", async ({ page }) => {
    // Navigate without injecting session
    await page.addInitScript(() => {
      localStorage.removeItem("bayes-session");
    });
    await page.goto("/portfolio");

    await expect(
      page.getByText("Set your Account ID in the header to view your portfolio."),
    ).toBeVisible();
  });
});
