const { test, expect } = require("@playwright/test");
const { execFileSync, spawn } = require("child_process");
const { existsSync, readdirSync } = require("fs");
const { join } = require("path");

const root = join(__dirname, "..", "..", "..");
const outputDir = join(root, "test-results", "visual-review-browser");
const port = 8877;
let server;

test.beforeAll(async () => {
  execFileSync(
    "python",
    [
      "-m", "backend.app.cli", "building-review",
      "--input", "resources/datasets/manifests/sample_mass_office_commercial.json",
      "--output-dir", outputDir,
    ],
    { cwd: join(root, "products", "plan"), stdio: "pipe" },
  );
  server = spawn("python", ["-m", "http.server", String(port), "--directory", outputDir], {
    cwd: root,
    stdio: "ignore",
  });
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (existsSync(join(outputDir, "index.html"))) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("visual-review output was not generated");
});

test.afterAll(() => server?.kill());

test("CAD layer manager controls inline drawing layers", async ({ page }) => {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*.svg", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.continue();
  });
  const floorDir = join(outputDir, "floor_001");
  const floorHtml = readdirSync(floorDir).find((name) => name.endsWith(".html"));
  await page.goto(`http://127.0.0.1:${port}/floor_001/${floorHtml}`, { waitUntil: "domcontentloaded" });

  const rooms = page.locator('#cad-layer-manager input[data-layer="rooms"]');
  await rooms.click();
  await expect(rooms).not.toBeChecked();
  await expect(page.locator('.drawing-pane [data-layer="rooms"]').first()).toHaveCSS("display", "none");

  const layers = [
    "grid",
    "rooms",
    "circulation",
    "core",
    "structure",
    "envelope",
    "door-openings",
    "furniture",
    "fixtures",
    "egress",
    "dimensions",
    "text-labels",
  ];
  for (const layer of layers) {
    const checkbox = page.locator(`#cad-layer-manager input[data-layer="${layer}"]`);
    if (layer !== "rooms") await checkbox.click();
    await expect(checkbox).not.toBeChecked();
    await expect(page.locator(`.drawing-pane [data-layer="${layer}"]`).first()).toHaveCSS("display", "none");
    await checkbox.click();
    await expect(checkbox).toBeChecked();
    await expect(page.locator(`.drawing-pane [data-layer="${layer}"]`).first()).not.toHaveCSS("display", "none");
  }

  const selectedRooms = page.locator('#cad-layer-manager .layer-select[data-layer="rooms"]');
  await selectedRooms.click();
  await expect(selectedRooms).toHaveAttribute("aria-pressed", "true");

  await page.locator('#cad-layer-manager input[data-layer="egress"]').click();
  await expect(page.locator('#cad-layer-manager input[data-layer="egress"]')).not.toBeChecked();
  await page.reload();
  await expect(page.locator('#cad-layer-manager input[data-layer="egress"]')).toBeChecked();
  await expect(page.locator('.drawing-pane [data-layer="egress"]').first()).not.toHaveCSS(
    "display",
    "none",
  );

  const floorTwoDir = join(outputDir, "floor_002");
  const floorTwoHtml = readdirSync(floorTwoDir).find((name) => name.endsWith(".html"));
  await page.goto(`http://127.0.0.1:${port}/floor_002/${floorTwoHtml}`);
  await expect(page.locator('#cad-layer-manager input[data-layer="egress"]')).toBeChecked();
  await expect(page.locator('.drawing-pane [data-layer="egress"]').first()).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(async () => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(page.locator("#cad-layer-manager")).toBeVisible();
  for (const layer of layers) {
    const checkbox = page.locator(`#cad-layer-manager input[data-layer="${layer}"]`);
    await checkbox.click();
    await expect(checkbox).not.toBeChecked();
    await checkbox.click();
    await expect(checkbox).toBeChecked();
  }
  const controlBounds = await page.locator("#cad-layer-manager").boundingBox();
  expect(controlBounds).not.toBeNull();
  expect(controlBounds.x + controlBounds.width).toBeLessThanOrEqual(376.5);
  for (const button of await page.locator("#cad-layer-manager button").all()) {
    const bounds = await button.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds.x).toBeGreaterThanOrEqual(controlBounds.x);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(
      controlBounds.x + controlBounds.width + 0.5,
    );
  }
  await expect(page.locator("#room-form-report th").first()).toHaveCSS("padding-left", "10px");
  expect(errors).toEqual([]);
});
