import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 800 });
  await page.route("**/api/providers", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ providers: [] })
  }));
  await page.goto("/");
});

test("narrow navigation dialog traps focus, hides its background, and restores the menu trigger", async ({ page }) => {
  const trigger = page.locator(".menu-button");
  await trigger.focus();
  await trigger.press("Enter");

  const dialog = page.getByRole("dialog", { name: "Workspace navigation" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".topbar")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".workspace-grid > .agent-workspace")).toHaveAttribute("aria-hidden", "true");
  await expect(dialog.getByRole("button", { name: "Close navigation" })).toBeFocused();

  await page.keyboard.press("Shift+Tab");
  await expectFocusWithin(page, dialog);
  await page.keyboard.press("Tab");
  await expectFocusWithin(page, dialog);
  await page.keyboard.press("Escape");

  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("compact CAD artifact dialog traps focus, hides its background, and restores its trigger", async ({ page }) => {
  const trigger = page.locator(".artifact-toggle");
  await trigger.focus();
  await trigger.press("Enter");

  const dialog = page.getByRole("dialog", { name: "CAD 아티팩트" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".topbar")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".workspace-grid > .agent-workspace")).toHaveAttribute("aria-hidden", "true");
  await expectFocusWithin(page, dialog);

  await page.keyboard.press("Shift+Tab");
  await expectFocusWithin(page, dialog);
  await page.keyboard.press("Tab");
  await expectFocusWithin(page, dialog);
  await page.keyboard.press("Escape");

  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("breakpoint transition keeps one modal owner with focus trap and Escape restoration", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 });
  await page.reload();
  await page.locator(".menu-button").click();
  await expect(page.locator(".workspace-sidebar")).toBeVisible();
  await expect(page.locator(".cad-artifact")).toBeVisible();

  await page.setViewportSize({ width: 800, height: 800 });

  const dialogs = page.getByRole("dialog");
  await expect(dialogs).toHaveCount(1);
  await expect(page.getByRole("dialog", { name: "CAD 아티팩트" })).toBeVisible();
  await expect(page.locator(".topbar")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".workspace-grid > .agent-workspace")).toHaveAttribute("aria-hidden", "true");
  await expectFocusWithin(page, page.getByRole("dialog", { name: "CAD 아티팩트" }));

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".artifact-toggle")).toBeFocused();
});

async function expectFocusWithin(page: Page, dialog: ReturnType<Page["getByRole"]>) {
  await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
}
