const { test, expect } = require("@playwright/test");

test("delivers a real reviewed PLANM run through the product UI", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByLabel("Project ID").fill("playwright-live-planm");
  await page.getByRole("button", { name: "Generate alternatives" }).click();

  await expect(page.getByText("alternative-a", { exact: true })).toBeVisible({ timeout: 90000 });
  await expect(page.getByText("alternative-c", { exact: true })).toBeVisible();
  const previews = page.locator(".drawing-frame img");
  await expect(previews).toHaveCount(2);
  expect(await previews.first().evaluate((image) => image.naturalWidth)).toBeGreaterThan(400);

  await page.getByRole("button", { name: "Approve alternative-a" }).click();
  await expect(page.getByText("Approved for delivery")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download delivery manifest" })).toBeVisible();
  await page.getByRole("button", { name: "Prepare layered DXF" }).click();
  await expect(page.getByText("DXF ready")).toBeVisible();
  await page.getByRole("button", { name: "Run DWG inspection" }).click();
  await expect(page.getByText("DWG verified")).toBeVisible({ timeout: 90000 });
  await expect(page.getByText(/grounded entities on F001_ROOMS; 0 warnings/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("live-approved-planm.png"), fullPage: true });
});
