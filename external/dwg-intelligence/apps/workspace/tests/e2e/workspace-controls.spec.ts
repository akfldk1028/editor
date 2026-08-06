import { expect, test } from "@playwright/test";

test("workspace keyboard and outside-click controls remain stable", async ({ page }) => {
  await page.route("**/api/providers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ providers: [] })
    })
  );
  await page.goto("/");

  await expect(page.getByLabel("전체 도면 검색")).toBeVisible();
  await page.keyboard.press("Control+K");
  await expect(page.getByLabel("전체 도면 검색")).toBeFocused();

  await page.getByRole("button", { name: "설정" }).click();
  await expect(page.getByRole("dialog", { name: "뷰어 설정" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "뷰어 설정" })).toBeHidden();

  await page.getByRole("button", { name: "알림" }).click();
  await expect(page.getByRole("status")).toBeVisible();
  await page.getByTestId("cad-canvas").click({ position: { x: 200, y: 200 } });
  await expect(page.getByRole("status")).toBeHidden();
});
