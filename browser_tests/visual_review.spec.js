const { test, expect } = require("@playwright/test");
const { execFileSync, spawn } = require("child_process");
const { existsSync, readdirSync } = require("fs");
const { join } = require("path");

const root = join(__dirname, "..");
const outputDir = join(root, "test-results", "visual-review-browser");
const port = 8877;
let server;

test.beforeAll(async () => {
  execFileSync(
    "python",
    [
      "-m", "backend.app.cli", "building-review",
      "--input", "datasets/manifests/sample_mass_office_commercial.json",
      "--output-dir", outputDir,
    ],
    { cwd: root, stdio: "pipe" },
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

test("working layer controls synchronize before and after iframe load", async ({ page }) => {
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

  const rooms = page.locator('[data-layer="rooms"]');
  await rooms.click();
  await expect(rooms).toHaveAttribute("aria-pressed", "false");
  const frame = page.frameLocator("#floor-plan");
  await expect(frame.locator('[data-layer="rooms"]')).toHaveCSS("display", "none");

  for (const layer of ["rooms", "circulation", "door-openings", "text-labels"]) {
    const button = page.locator(`#working-layer-controls [data-layer="${layer}"]`);
    if (layer !== "rooms") await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "false");
    await expect(frame.locator(`[data-layer="${layer}"]`).first()).toHaveCSS("display", "none");
    await button.click();
    await expect(button).toHaveAttribute("aria-pressed", "true");
    await expect(frame.locator(`[data-layer="${layer}"]`).first()).not.toHaveCSS("display", "none");
  }
  expect(errors).toEqual([]);
});
