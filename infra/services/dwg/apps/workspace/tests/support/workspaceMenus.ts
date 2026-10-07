import type { Page } from "@playwright/test";

/**
 * Secondary artifact controls (search, version, copy, download, maximize,
 * reset, and the Evidence / Export / Warnings views) live in the artifact's
 * overflow menu; these helpers open it before reaching for them.
 */
export async function openArtifactMenu(page: Page) {
  const menu = page.locator(".artifact-menu");
  if (await menu.evaluate((element) => element.matches(":popover-open"))) return menu;
  await page.getByRole("button", { name: "아티팩트 메뉴" }).click();
  return menu;
}

/** Opens a secondary artifact view (근거, 내보내기, 경고) from the menu. */
export async function openArtifactView(page: Page, name: "근거" | "내보내기" | "경고") {
  const menu = await openArtifactMenu(page);
  await menu.getByRole("button", { name, exact: false }).click();
}

/** The model chip in the composer opens the provider choices. */
export async function openModelMenu(page: Page) {
  await page.getByRole("button", { name: /AI 모델/ }).click();
  return page.locator(".model-menu");
}
