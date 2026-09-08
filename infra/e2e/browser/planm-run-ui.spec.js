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

const haltedRun = {
  contract_version: "planm-run/v1",
  run_id: "fedcba9876543210fedcba9876543210",
  project_id: "narrow-corner",
  status: "retryable",
  stage: "alternatives",
  approved_alternative_id: null,
  violations: [
    {
      code: "insufficient_accepted_alternatives",
      message: "at least two accepted alternatives are required",
    },
  ],
};

const haltedAlternatives = {
  project_id: "narrow-corner",
  accepted_count: 1,
  accepted_alternative_ids: ["alternative-a"],
  alternatives: [
    {
      alternative_id: "alternative-a",
      strategy: "rear-right-core-single-spine",
      rank: 1,
      score: 0.9,
      accepted: true,
      internal_validation: "pass",
      render_validation: "pass",
      regulatory_screening: "not_checked",
    },
  ],
  rejected_families: [
    {
      family: "side-mid-core-longitudinal-spine",
      reasons: ["too few accessible room rectangles"],
    },
    {
      family: "front-left-core-double-loaded",
      reasons: ["quality distinctness 0.128 below the required separation"],
    },
  ],
};

test("shows why a halted run stopped instead of an empty board", async ({ page }, testInfo) => {
  await page.route("**/api/v1/planm/runs", async (route) => {
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(haltedRun) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(haltedAlternatives) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives/*/preview", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/svg+xml", body: "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'><rect width='100%' height='100%' fill='white'/><path d='M80 80H720V370H80Z' fill='none' stroke='black' stroke-width='8'/></svg>" });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "PLANM Planning" }).click();
  await page.getByRole("button", { name: "Generate alternatives" }).click();

  await expect(page.getByText("Halted at alternatives")).toBeVisible();
  await expect(page.getByText("insufficient_accepted_alternatives")).toBeVisible();
  await expect(page.getByText("at least two accepted alternatives are required")).toBeVisible();
  await expect(page.getByText("1 of 2 accepted")).toBeVisible();
  await expect(page.getByText("side-mid-core-longitudinal-spine")).toBeVisible();
  await expect(page.getByText("too few accessible room rectangles")).toBeVisible();
  await expect(page.getByText("quality distinctness 0.128 below the required separation")).toBeVisible();
  await expect(page.getByText("alternative-a", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve alternative-a" })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("halted-planm.png"), fullPage: true });
});

test("submits a non-rectangular plate and the asserted code facts", async ({ page }, testInfo) => {
  let submitted = null;
  await page.route("**/api/v1/planm/runs", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(run) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(alternatives) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives/*/preview", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/svg+xml", body: "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'><rect width='100%' height='100%' fill='white'/></svg>" });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "PLANM Planning" }).click();
  await page.getByLabel("Plate shape").selectOption("l");
  await page.getByLabel("Width m", { exact: true }).fill("40");
  await page.getByLabel("Depth m", { exact: true }).fill("24");
  await page.getByLabel("Cut width m", { exact: true }).fill("12");
  await page.getByLabel("Cut depth m", { exact: true }).fill("7.2");
  await page.getByLabel("Jurisdiction").selectOption("KR");
  await page.getByLabel("Analysis as-of date").fill("2026-07-28");
  await page.getByLabel("Travel limit").selectOption("general_30");
  await page.getByLabel("Sprinkler protection").selectOption("qualifying");
  await page.getByRole("button", { name: "Generate alternatives" }).click();

  await expect(page.getByText("alternative-a", { exact: true })).toBeVisible();
  expect(submitted.mass.footprint_polygon).toEqual([
    [0, 0],
    [40, 0],
    [40, 16.8],
    [28, 16.8],
    [28, 24],
    [0, 24],
  ]);
  expect(submitted.mass.site_edges).toEqual([{ edge_index: 0, kind: "street" }]);
  expect(submitted.mass.building_code_context).toEqual({
    jurisdiction: "KR",
    effective_date: "2026-07-28",
    travel_limit_classification: "general_30",
    sprinklered: true,
    qualifying_sprinkler_protection: true,
    floor_facts: [],
  });
  await page.screenshot({ path: testInfo.outputPath("l-plate-brief.png"), fullPage: true });
});

test("omits the code context when no code fact is asserted", async ({ page }) => {
  let submitted = null;
  await page.route("**/api/v1/planm/runs", async (route) => {
    submitted = route.request().postDataJSON();
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(run) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(alternatives) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives/*/preview", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/svg+xml", body: "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'><rect width='100%' height='100%' fill='white'/></svg>" });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "PLANM Planning" }).click();
  await page.getByRole("button", { name: "Generate alternatives" }).click();

  await expect(page.getByText("alternative-a", { exact: true })).toBeVisible();
  expect(submitted.mass.footprint_polygon).toEqual([[0, 0], [30, 0], [30, 12], [0, 12]]);
  expect(submitted.mass.building_code_context).toBeUndefined();
});

test("names the code facts a delivered run still could not resolve", async ({ page }) => {
  await page.route("**/api/v1/planm/runs", async (route) => {
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ ...run, unresolved_facts: ["floor_code_context"] }),
    });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(alternatives) });
  });
  await page.route("**/api/v1/planm/runs/*/alternatives/*/preview", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/svg+xml", body: "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'><rect width='100%' height='100%' fill='white'/></svg>" });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "PLANM Planning" }).click();
  await page.getByRole("button", { name: "Generate alternatives" }).click();

  await expect(page.getByText("Unresolved code facts")).toBeVisible();
  await expect(page.getByText("floor_code_context")).toBeVisible();
});

// Every footprint the alternatives sweep measures, so the brief can reproduce a
// measured case exactly instead of approximating it.
const sweepFootprints = [
  {
    name: "L-36x26",
    form: { shape: "l", width: 36, depth: 26, cutWidth: 18, cutDepth: 12 },
    polygon: [[0, 0], [36, 0], [36, 14], [18, 14], [18, 26], [0, 26]],
  },
  {
    name: "L-large",
    form: { shape: "l", width: 48, depth: 40, cutWidth: 24, cutDepth: 20 },
    polygon: [[0, 0], [48, 0], [48, 20], [24, 20], [24, 40], [0, 40]],
  },
  {
    name: "U-shape",
    form: { shape: "u", width: 44, depth: 28, cutWidth: 20, cutDepth: 16 },
    polygon: [[0, 0], [44, 0], [44, 28], [32, 28], [32, 12], [12, 12], [12, 28], [0, 28]],
  },
  {
    name: "T-shape",
    form: { shape: "t", width: 44, depth: 30, cutWidth: 28, cutDepth: 16 },
    polygon: [[0, 0], [44, 0], [44, 14], [30, 14], [30, 30], [14, 30], [14, 14], [0, 14]],
  },
  {
    name: "notched",
    form: { shape: "u", width: 40, depth: 26, cutWidth: 12, cutDepth: 8 },
    polygon: [[0, 0], [40, 0], [40, 26], [26, 26], [26, 18], [14, 18], [14, 26], [0, 26]],
  },
  {
    name: "chamfered",
    form: { shape: "chamfered", width: 40, depth: 26, cutWidth: 6, cutDepth: 6 },
    polygon: [[6, 0], [34, 0], [40, 6], [40, 20], [34, 26], [6, 26], [0, 20], [0, 6]],
  },
  {
    name: "sloped",
    form: { shape: "sloped", width: 40, depth: 26, cutWidth: 16, cutDepth: 8 },
    polygon: [[0, 0], [40, 0], [40, 18], [24, 26], [0, 26]],
  },
];

for (const shape of sweepFootprints) {
  test(`reproduces the ${shape.name} footprint the sweep measures`, async ({ page }) => {
    let submitted = null;
    await page.route("**/api/v1/planm/runs", async (route) => {
      submitted = route.request().postDataJSON();
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(run) });
    });
    await page.route("**/api/v1/planm/runs/*/alternatives", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(alternatives) });
    });
    await page.route("**/api/v1/planm/runs/*/alternatives/*/preview", async (route) => {
      await route.fulfill({ status: 200, contentType: "image/svg+xml", body: "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450'><rect width='100%' height='100%' fill='white'/></svg>" });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "PLANM Planning" }).click();
    await page.getByLabel("Plate shape").selectOption(shape.form.shape);
    await page.getByLabel("Width m", { exact: true }).fill(String(shape.form.width));
    await page.getByLabel("Depth m", { exact: true }).fill(String(shape.form.depth));
    if (shape.form.shape === "chamfered") {
      await page.getByLabel("Chamfer m", { exact: true }).fill(String(shape.form.cutWidth));
    } else {
      await page.getByLabel("Cut width m", { exact: true }).fill(String(shape.form.cutWidth));
      await page.getByLabel("Cut depth m", { exact: true }).fill(String(shape.form.cutDepth));
    }
    await page.getByRole("button", { name: "Generate alternatives" }).click();

    await expect(page.getByText("alternative-a", { exact: true })).toBeVisible();
    expect(submitted.mass.footprint_polygon).toEqual(shape.polygon);
    // Edge 0 is the pinned street frontage on every family.
    expect(submitted.mass.site_edges).toEqual([{ edge_index: 0, kind: "street" }]);
  });
}
