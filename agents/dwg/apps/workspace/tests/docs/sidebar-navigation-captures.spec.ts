import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

import {
  documentationCaptureDirectory,
  documentationCapturePath
} from "../support/repositoryOutputPaths.ts";

test.describe.configure({ mode: "serial" });

test("captures desktop and narrow sidebar navigation", async ({ page }) => {
  await mkdir(documentationCaptureDirectory, { recursive: true });
  await mockSkills(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("tree", { name: "Drawing hierarchy" })).toBeVisible();
  await stabilize(page);
  await capture(page, "sidebar-desktop.png");

  await page.getByRole("tab", { name: "Skills" }).click();
  await expect(page.getByRole("region", { name: "Skills" })).toContainText("inspect-drawing");
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.reload();
  await page.locator(".menu-button").click();
  await expect(page.locator(".workspace-sidebar.overlay")).toBeVisible();
  await capture(page, "sidebar-narrow.png");
});

async function mockSkills(page: Page) {
  await page.route("**/api/skills", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      skills: [{
        id: "inspect-drawing",
        version: "1.0.0",
        compatible: true,
        permissions: ["read"],
        recentStatus: "passed"
      }]
    })
  }));
}

async function stabilize(page: Page) {
  await page.addStyleTag({ content: "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}" });
}

async function capture(page: Page, fileName: string) {
  await stabilize(page);
  await page.evaluate(async () => {
    await document.fonts.ready;
    (document.activeElement as HTMLElement | null)?.blur();
  });
  await page.screenshot({ path: documentationCapturePath(fileName), fullPage: true, animations: "disabled" });
}
