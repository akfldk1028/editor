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

  const dialog = page.getByRole("dialog", { name: "작업 탐색" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".topbar")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator(".workspace-grid > .agent-workspace")).toHaveAttribute("aria-hidden", "true");
  await expect(dialog.getByRole("button", { name: "탐색 닫기" })).toBeFocused();

  await page.keyboard.press("Shift+Tab");
  await expectFocusWithin(page, dialog);
  await page.keyboard.press("Tab");
  await expectFocusWithin(page, dialog);
  await page.keyboard.press("Escape");

  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("a layout mode change closes the drawer and leaves no modal behind", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 });
  await page.reload();
  await page.locator(".menu-button").click();
  await expect(page.getByRole("dialog", { name: "작업 탐색" })).toBeVisible();
  await expect(page.locator(".cad-artifact")).toBeVisible();

  await page.setViewportSize({ width: 700, height: 800 });

  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".topbar")).not.toHaveAttribute("aria-hidden", "true");
  await expect(page.getByRole("main", { name: "대화" })).toBeVisible();
});

test("widening to the wide layout puts the sidebar inline", async ({ page }) => {
  await page.locator(".menu-button").click();
  await expect(page.getByRole("dialog", { name: "작업 탐색" })).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 800 });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "작업 탐색" })).toBeVisible();
});

async function expectFocusWithin(page: Page, dialog: ReturnType<Page["getByRole"]>) {
  await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
}
