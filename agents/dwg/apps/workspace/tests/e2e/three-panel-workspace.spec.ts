import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/providers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ providers: [] })
    })
  );
  await page.goto("/");
});

test("uses the Claude-style project, conversation, and artifact order", async ({ page }) => {
  const sidebar = page.getByRole("complementary", { name: "Workspace navigation" });
  const conversation = page.getByRole("main", { name: "대화" });
  const artifact = page.getByRole("region", { name: "CAD 아티팩트" });

  await expect(sidebar).toBeVisible();
  await expect(conversation).toBeVisible();
  await expect(artifact).toBeVisible();

  const [sidebarBox, conversationBox, artifactBox] = await Promise.all([
    sidebar.boundingBox(),
    conversation.boundingBox(),
    artifact.boundingBox()
  ]);
  expect(sidebarBox!.x).toBeLessThan(conversationBox!.x);
  expect(conversationBox!.x).toBeLessThan(artifactBox!.x);
  await expect(page.locator(".inspection-dock")).toHaveCount(0);
});

test("artifact panel switches tabs, resizes, and maximizes", async ({ page }) => {
  const artifact = page.getByRole("region", { name: "CAD 아티팩트" });
  const initial = await artifact.boundingBox();

  await page.getByRole("tab", { name: "Findings", exact: false }).click();
  await expect(page.getByText("검사를 실행하면 근거가 표시됩니다.")).toBeVisible();

  const handle = page.getByRole("separator", { name: "CAD 아티팩트 너비 조절" });
  await handle.press("ArrowLeft");
  const resized = await artifact.boundingBox();
  expect(resized!.width).toBeGreaterThan(initial!.width);

  await page.getByRole("button", { name: "아티팩트 최대화" }).click();
  await expect(artifact).toHaveAttribute("data-maximized", "true");
  await page.keyboard.press("Escape");
  await expect(artifact).toHaveAttribute("data-maximized", "false");
});

test("theme preference is applied and persisted", async ({ page }) => {
  await page.getByRole("button", { name: "설정" }).click();
  await page.getByLabel("테마").selectOption("dark");
  await expect(page.locator(".app-shell")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByTestId("cad-canvas")).toHaveCSS("background-color", "rgb(23, 26, 28)");
  await expect(page.getByRole("main", { name: "대화" })).toHaveCSS("background-color", "rgb(33, 31, 28)");

  await page.reload();
  await expect(page.locator(".app-shell")).toHaveAttribute("data-theme", "dark");
});

test("narrow workspace opens the project tree as an overlay", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.reload();

  const menu = page.getByRole("button", { name: "탐색 열기" });
  await expect(page.getByRole("dialog", { name: "Workspace navigation" })).toHaveCount(0);
  await menu.focus();
  await menu.click();
  const sidebar = page.getByRole("dialog", { name: "Workspace navigation" });
  await expect(sidebar).toHaveClass(/overlay/);
  await expect(sidebar).toHaveAttribute("aria-modal", "true");
  await expect(sidebar.getByRole("button", { name: "Close navigation" })).toBeFocused();
  await expect(page.locator(".agent-workspace")).toBeVisible();
  await expect(page.locator(".cad-artifact")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sidebar).toHaveCount(0);
  await expect(menu).toBeFocused();

  await menu.click();
  await page.getByRole("button", { name: "탐색 닫기" }).click({ position: { x: 900, y: 300 } });
  await expect(page.getByRole("dialog", { name: "Workspace navigation" })).toHaveCount(0);
  await expect(menu).toBeFocused();
});

test("compact workspace opens CAD as a full artifact overlay", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 700 });
  await page.reload();

  await expect(page.getByRole("main", { name: "대화" })).toBeVisible();
  await expect(page.getByRole("region", { name: "CAD 아티팩트" })).toBeHidden();
  await page.getByRole("button", { name: "CAD 아티팩트 열기" }).click();
  await expect(page.getByRole("dialog", { name: "CAD 아티팩트" })).toBeVisible();
  await page.getByRole("button", { name: "CAD 아티팩트 닫기" }).click();
  await expect(page.getByRole("region", { name: "CAD 아티팩트" })).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(800);
});
