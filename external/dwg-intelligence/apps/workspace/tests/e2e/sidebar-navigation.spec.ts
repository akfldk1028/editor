import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import type { CadIndex } from "@dwg/contracts";

const indexFixture = JSON.parse(readFileSync(
  fileURLToPath(new URL("../../public/data/export_sample.index.json", import.meta.url)),
  "utf8"
)) as CadIndex;

const skills = [
  {
    id: "inspect-drawing",
    version: "1.0.0",
    compatible: true,
    permissions: ["read"],
    recentStatus: "passed"
  },
  {
    id: "compare-drawings",
    version: "1.0.0",
    compatible: false,
    permissions: ["read", "propose-edit"],
    recentStatus: "failed"
  }
];

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockSkills(page, { skills });
});

test("navigates project sessions and skills tabs with keyboard focus and persistence", async ({ page }) => {
  await page.goto("/");

  const sidebar = page.getByRole("complementary", { name: "Workspace navigation" });
  const tabs = sidebar.getByRole("tablist", { name: "Workspace navigation sections" });
  await expect(tabs.getByRole("tab", { name: "Project" })).toHaveAttribute("aria-selected", "true");
  await expect(sidebar.getByRole("tree", { name: "Drawing hierarchy" })).toBeVisible();

  await tabs.getByRole("tab", { name: "Project" }).press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "Sessions" })).toBeFocused();
  await expect(tabs.getByRole("tab", { name: "Sessions" })).toHaveAttribute("aria-selected", "true");
  await expect(sidebar.getByRole("region", { name: "Sessions" })).toBeVisible();

  await tabs.getByRole("tab", { name: "Sessions" }).press("End");
  await expect(tabs.getByRole("tab", { name: "Skills" })).toBeFocused();
  await expect(sidebar.getByRole("region", { name: "Skills" })).toContainText("inspect-drawing");
  await expect(sidebar.getByText("Incompatible")).toBeVisible();
  await expect(sidebar.getByText("Failed")).toBeVisible();

  await page.reload();
  await expect(page.getByRole("tab", { name: "Skills" })).toHaveAttribute("aria-selected", "true");
});

test("renders grounded drawing hierarchy with actual visibility, aligned metadata and long-name help", async ({ page }) => {
  await page.goto("/");
  const sidebar = page.getByRole("complementary", { name: "Workspace navigation" });
  const tree = sidebar.getByRole("tree", { name: "Drawing hierarchy" });

  await expect(tree.getByRole("treeitem", { name: /export_sample\.dwg/ })).toBeVisible();
  await expect(tree.getByRole("treeitem", { name: /Layouts/ })).toBeVisible();
  await expect(tree.getByRole("treeitem", { name: /Layers/ })).toBeVisible();

  const layer = tree.locator(".project-layer-row").first();
  await expect(layer.getByRole("button", { name: /Hide layer/ })).toHaveAttribute("aria-pressed", "false");
  await expect(layer.locator(".project-layer-lock")).toHaveText("Unlocked");
  await expect(layer.locator(".project-layer-color")).toContainText("ACI 7");
  await expect(layer.locator(".project-layer-swatch")).toHaveCSS("background-color", "rgb(0, 0, 0)");
  await expect(layer.locator(".project-layer-count")).toHaveText("229");

  await layer.getByRole("button", { name: /Hide layer/ }).click();
  await expect(layer.getByRole("button", { name: /Show layer/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".viewer-status")).toContainText("0 visible / 22 total");

  const longLayer = tree.locator(".project-layer-name[title]").first();
  await expect(longLayer).toHaveAttribute("title", /.+/);
});

test("source-hidden and frozen layers remain unavailable while null metadata stays unknown", async ({ page }) => {
  const index: CadIndex = {
    ...indexFixture,
    layers: indexFixture.layers.map((layer) => {
      if (layer.name === "0") {
        return { ...layer, visible: false, frozen: false, locked: null, color: null };
      }
      if (layer.name === "Defpoints") {
        return { ...layer, visible: true, frozen: true, locked: true, color: 1 };
      }
      return layer;
    })
  };
  await page.route("**/api/drawing", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(index)
  }));
  await page.goto("/");

  const sourceHidden = page.locator(".project-layer-row").filter({ hasText: "0" }).first();
  const frozen = page.locator(".project-layer-row").filter({ hasText: "Defpoints" }).first();
  await expect(sourceHidden.getByRole("button", { name: "Layer 0 is hidden in source" })).toBeDisabled();
  await expect(sourceHidden.locator(".project-layer-lock")).toHaveText("Unknown");
  await expect(sourceHidden.locator(".project-layer-color")).toHaveText("Unknown");
  await expect(frozen.getByRole("button", { name: "Layer Defpoints is frozen" })).toBeDisabled();
  await expect(frozen.locator(".project-layer-lock")).toHaveText("Locked");
  await expect(frozen.locator(".project-layer-color")).toContainText("ACI 1");
  await expect(page.locator(".viewer-status")).toContainText("0 visible / 22 total");
});

test("keeps search sticky while project content and sessions scroll independently", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("dwg.workspace-sessions.v1", JSON.stringify({
      sessions: Array.from({ length: 20 }, (_, index) => ({
        id: `session-${index}`,
        provider: "codex",
        providerSessionId: null,
        drawingPath: "export_sample.dwg",
        title: `Session ${index}`,
        updatedAt: `2026-07-30T00:${String(index).padStart(2, "0")}:00.000Z`,
        messages: []
      }))
    }));
  });
  await page.goto("/");

  const sidebar = page.getByRole("complementary", { name: "Workspace navigation" });
  const search = sidebar.getByLabel("Search workspace");
  const projectScroller = sidebar.locator(".project-navigation-scroll");
  await expect(search).toBeVisible();
  await expect(projectScroller).toHaveCSS("overflow-y", "auto");

  await sidebar.getByRole("tab", { name: "Sessions" }).click();
  const sessionScroller = sidebar.locator(".session-navigation-scroll");
  expect(await sessionScroller.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  await expect(sessionScroller).toHaveCSS("overflow-y", "auto");
  await expect(search).toBeVisible();
});

test("reports skill loading empty and error states", async ({ page }) => {
  await page.route("**/api/skills", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ skills: [] }) });
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "Skills" }).click();
  await expect(page.getByText("Loading skills…")).toBeVisible();
  await expect(page.getByText("No skills available.")).toBeVisible();

  await page.unroute("**/api/skills");
  await page.route("**/api/skills", (route) => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "offline" }) }));
  await page.reload();
  await expect(page.getByText("Unable to load skills: offline")).toBeVisible();
});

async function mockSkills(page: Page, response: { skills: typeof skills }) {
  await page.route("**/api/skills", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(response)
  }));
}
