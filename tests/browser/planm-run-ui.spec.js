const { test, expect } = require("@playwright/test");

const run = {
  contract_version: "planm-run/v1",
  run_id: "0123456789abcdef0123456789abcdef",
  project_id: "seongsu-corner",
  status: "delivered",
  stage: "delivered",
  approved_alternative_id: null,
  violations: [],
};

const alternatives = {
  project_id: "seongsu-corner",
  accepted_count: 2,
  accepted_alternative_ids: ["alternative-a", "alternative-c"],
  alternatives: [
    {
      alternative_id: "alternative-a",
      strategy: "rear-right-core-single-spine",
      rank: 1,
      score: 0.94,
      accepted: true,
      internal_validation: "pass",
      render_validation: "pass",
      regulatory_screening: "not_checked",
    },
    {
      alternative_id: "alternative-c",
      strategy: "side-mid-core-longitudinal-spine",
      rank: 2,
      score: 0.91,
      accepted: true,
      internal_validation: "pass",
      render_validation: "pass",
      regulatory_screening: "not_checked",
    },
  ],
};

test("creates a PLANM run, compares alternatives, and approves one", async ({ page }, testInfo) => {
  await page.route("**/api/v1/planm/runs", async (route) => {
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(run) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(alternatives) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives/*/preview", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/svg+xml", body: "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'><rect width='100%' height='100%' fill='white'/><path d='M80 80H720V370H80Z M400 80V370 M80 220H720' fill='none' stroke='black' stroke-width='8'/></svg>" });
  });
  await page.route("**/api/v1/planm/runs/*/approval", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ ...run, status: "approved", approved_alternative_id: "alternative-a" }),
    });
  });
  await page.route("**/api/v1/planm/runs/*/dwg/handoff", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({
      contract_version: "planm-cad-handoff/v1", alternative_id: "alternative-a",
      drawing_path: "cad-handoff/approved-plan.dxf", source_floor_count: 5,
      entity_count: 2463, units: "meters", dwg_validation: "not_checked",
    }) });
  });
  await page.route("**/api/v1/planm/runs/*/dwg/inspection", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({
      contract_version: "planm-dwg-inspection/v1", alternative_id: "alternative-a",
      drawing_path: "cad-handoff/approved-plan.dxf", layer: "F001_ROOMS", status: "passed",
      evidence: { warning_codes: [], result: { matches: Array.from({ length: 36 }, (_, index) => ({
        id: `h:${index + 1}`, handle: String(index + 1), type: "LINE", layer: "F001_ROOMS",
        bbox: { min: [0, 0, 0], max: [10, 0, 0] }, reason: "layer equals query", confidence: 1,
      })) } },
    }) });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "PLANM Planning" }).click();
  await expect(page.getByRole("heading", { name: "Plans with proof." })).toBeVisible();
  await page.getByRole("button", { name: "Generate alternatives" }).click();
  await expect(page.getByText("alternative-a", { exact: true })).toBeVisible();
  await expect(page.getByText("alternative-c", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Approve alternative-a" }).click();
  await expect(page.getByText("Approved for delivery")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download delivery manifest" })).toBeVisible();
  await page.getByRole("button", { name: "Prepare layered DXF" }).click();
  await expect(page.getByText("DXF ready")).toBeVisible();
  await page.getByRole("button", { name: "Run DWG inspection" }).click();
  await expect(page.getByText("DWG verified")).toBeVisible();
  await expect(page.getByText("36 grounded entities on F001_ROOMS; 0 warnings")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("approved-planm.png"), fullPage: true });
});
