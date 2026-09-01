import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
});

test("uses the assembled export capability endpoint and separates report export from drawing Save As", async ({ page }) => {
  const capabilityStatus = await page.evaluate(async () => {
    const response = await fetch("/api/export/capabilities");
    return response.status;
  });
  expect(capabilityStatus).toBe(200);

  await page.getByRole("tab", { name: "Export", exact: true }).click();
  const panel = page.getByRole("region", { name: "Export" });
  await expect(panel.getByRole("heading", { name: "Report export" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Drawing Save As" })).toBeVisible();
  await expect(panel.getByRole("button", { name: /Download.*DWG/i })).toHaveCount(0);
  await expect(panel.getByRole("button", { name: "Choose destination" })).toBeVisible();
  await expect(panel.getByLabel("Base filename")).toBeVisible();
  await expect(panel.locator(".destination-status")).toContainText("Destination required");
});

test("keeps a 500 pixel conversation and exposes both keyboard resizers at 1280 by 800", async ({ page }) => {
  const conversation = page.getByRole("main", { name: "대화" });
  await expect(conversation).toBeVisible();
  expect((await conversation.boundingBox())!.width).toBeGreaterThanOrEqual(500);

  const sidebar = page.getByRole("separator", { name: "Sidebar width" });
  const artifact = page.locator(".artifact-resizer");
  await expect(sidebar).toHaveAttribute("tabindex", "0");
  await expect(artifact).toHaveAttribute("tabindex", "0");
  await sidebar.press("ArrowRight");
  await artifact.press("ArrowLeft");
  expect((await conversation.boundingBox())!.width).toBeGreaterThanOrEqual(500);
});

test("failed Save As consumes the selected grant and requires a new destination", async ({ page }) => {
  let saveAttempts = 0;
  await page.route("**/api/export/drawings", async (route) => {
    saveAttempts += 1;
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "CAD_SAVE_FAILED", message: "forced failure" } })
    });
  });
  await page.getByRole("tab", { name: "Export", exact: true }).click();
  const panel = page.getByRole("region", { name: "Export" });
  await panel.getByRole("button", { name: "Choose destination" }).click();
  const save = panel.getByRole("button", { name: "Save As DWG" });
  await save.click();

  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(panel.getByRole("status")).toContainText(
    "Destination grant used — choose again for another copy"
  );
  await expect(save).toBeDisabled();
  expect(saveAttempts).toBe(1);
});

test("disables every export control while a destination action is in flight", async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/export/destination-grants", async (route) => {
    await pending;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        grantId: "11111111-1111-4111-8111-111111111111",
        displayDirectory: "Exports",
        expiresAt: Date.now() + 60_000
      })
    });
  });
  await page.getByRole("tab", { name: "Export", exact: true }).click();
  const panel = page.getByRole("region", { name: "Export" });
  await panel.getByRole("button", { name: "Choose destination" }).click();

  await expect(panel.getByRole("button", { name: "Choose destination" })).toBeDisabled();
  await expect(panel.getByLabel("Base filename")).toBeDisabled();
  for (const button of await panel.getByRole("button").all()) {
    await expect(button).toBeDisabled();
  }

  release();
  await expect(panel.getByRole("status")).toContainText("Destination selected: Exports");
  await expect(panel.getByRole("button", { name: "Choose destination" })).toBeEnabled();
  await expect(panel.getByLabel("Base filename")).toBeEnabled();
});
