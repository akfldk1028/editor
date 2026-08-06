import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import {
  e2eArtifactDirectory,
  e2eArtifactPath
} from "../support/repositoryOutputPaths.ts";

const artifacts = e2eArtifactDirectory;

test("layer eye button hides and restores its CAD entities", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/providers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ providers: [] })
    })
  );
  await page.goto("/");

  const layerToggle = page.locator(".layer-visibility-button").first();
  await expect(layerToggle).toHaveAccessibleName("Hide layer 0");
  await expect(page.locator(".cad-entity")).toHaveCount(22);

  await layerToggle.click();
  await expect(page.locator(".cad-entity")).toHaveCount(0);
  await expect(layerToggle).toHaveAccessibleName("Show layer 0");
  await mkdir(artifacts, { recursive: true });
  await page.screenshot({
    path: e2eArtifactPath("layer-hidden-1440x900.png"),
    fullPage: true
  });

  await layerToggle.click();
  await expect(page.locator(".cad-entity")).toHaveCount(22);
  await expect(layerToggle).toHaveAccessibleName("Hide layer 0");
  await page.screenshot({
    path: e2eArtifactPath("layer-restored-1440x900.png"),
    fullPage: true
  });
});
