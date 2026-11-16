import { test, expect } from "@playwright/test";

// Key scenario only — assert observable user outcome, not pixels/snapshots.
test("home shows product name", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Orbit-like mini" })).toBeVisible();
});
