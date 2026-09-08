import { expect, test } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import type { CadIndex } from "@dwg/contracts";
import {
  e2eArtifactDirectory,
  e2eArtifactPath
} from "../support/repositoryOutputPaths.ts";

const artifacts = e2eArtifactDirectory;
const fixturePath = fileURLToPath(
  new URL("../../public/data/export_sample.index.json", import.meta.url)
);

async function fixture() {
  return JSON.parse(await readFile(fixturePath, "utf8")) as CadIndex;
}

async function prepare(page: import("@playwright/test").Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/providers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ providers: [] })
    })
  );
  await page.goto("/");
}

test("renders real v0.2 geometry and explicit fallbacks", async ({ page }) => {
  const index = await fixture();
  const modelCount = index.entities.filter(
    (entity) => entity.layout === "Model"
  ).length;

  await prepare(page);

  await expect(page.locator(".cad-entity")).toHaveCount(modelCount);
  await expect(page.getByRole("img", {
    name: `${modelCount}개 객체가 표시된 DWG 도면`
  })).toBeVisible();
  await expect(page.locator('[data-handle="23D"]'))
    .toHaveAttribute("data-geometry-kind", "line");
  await expect(page.locator('[data-handle="23E"]'))
    .toHaveAttribute("data-geometry-kind", "arc");
  await expect(page.locator('[data-handle="239"]'))
    .toHaveAttribute("data-geometry-kind", "lwpolyline");
  await expect(page.locator('[data-handle="591"]'))
    .toHaveAttribute("data-geometry-kind", "text");
  await expect(page.locator('[data-handle="347"]'))
    .toHaveAttribute("data-geometry-kind", "bbox");
  await expect(page.locator('[data-handle="3D6"]'))
    .toHaveAttribute("data-geometry-kind", "bbox");
  await expect(page.locator('[data-handle="3B6"]'))
    .toHaveAttribute("data-geometry-kind", "insert");
  expect(await page.locator('[data-handle="23C"]').evaluate(
    (element) => getComputedStyle(element).fill
  )).toBe("none");

  await mkdir(artifacts, { recursive: true });
  await page.screenshot({
    path: e2eArtifactPath("geometry-loaded-1440x900.png"),
    fullPage: true
  });
});

test("fits the drawing bounds on initial load", async ({ page }) => {
  await prepare(page);

  await expect(page.getByTestId("cad-canvas")).toHaveAttribute(
    "data-view",
    "fit"
  );
  await expect(page.locator("svg.cad-canvas")).not.toHaveAttribute(
    "viewBox",
    "-24 -12 148 126"
  );
});

test("bounds large SVG rendering while retaining a searched entity", async ({
  page
}) => {
  const index = await fixture();
  if (index.schemaVersion !== "cad-index/v0.2") {
    throw new Error("Expected a v0.2 fixture");
  }
  const template = index.entities.find(
    (entity) => entity.layout === "Model"
  );
  if (!template) throw new Error("Expected a model-space entity");
  const entities = Array.from({ length: 2002 }, (_, position) => ({
    ...template,
    id: `lod:${position}`,
    handle: `LOD-${position}`
  }));
  const largeIndex: CadIndex = {
    ...index,
    entities,
    summary: {
      ...index.summary,
      entityCount: entities.length,
      modelSpaceCount: entities.length,
      paperSpaceCount: 0
    }
  };
  await page.route("**/api/drawing", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(largeIndex)
    })
  );

  await prepare(page);

  await expect(page.locator(".cad-entity")).toHaveCount(2000);
  await page.getByLabel("전체 도면 검색").fill("LOD-2001");
  await expect(page.locator('[data-handle="LOD-2001"]')).toBeVisible();
  await expect(page.locator(".viewer-status")).toContainText(
    "2000 rendered / 2002 visible"
  );
});

test("layer visibility and handle highlighting apply to typed geometry", async ({
  page
}) => {
  const index = await fixture();
  const visibleAfterHide = index.entities.filter(
    (entity) => entity.layout === "Model" && entity.layer !== "0"
  ).length;

  await prepare(page);

  const defaultLayer = page.locator(".layer-row").filter({
    hasText: "0"
  }).first();
  const toggle = defaultLayer.locator(".layer-visibility-button");
  await toggle.click();
  await expect(page.locator(".cad-entity")).toHaveCount(visibleAfterHide);

  await toggle.click();
  await page.getByLabel("전체 도면 검색").fill("23E");
  await expect(page.locator('[data-handle="23E"]'))
    .toHaveClass(/highlighted/);
});

test("explorer exposes every indexed layout and the active schema", async ({
  page
}) => {
  const index = await fixture();
  const layoutCount = new Set(
    index.entities.map((entity) => entity.layout)
  ).size;

  await prepare(page);

  await expect(page.locator(".layout-row")).toHaveCount(layoutCount);
  await expect(page.locator(".project-navigation-footer")).toContainText("cad-index/v0.2");
});
