import { expect, test, type Locator, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/providers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ providers: [] })
    })
  );
});

test("uses readable conversation typography", async ({ page }) => {
  await page.goto("/");

  const promptSize = await page.locator(".conversation-empty span").evaluate(
    (element) => Number.parseFloat(getComputedStyle(element).fontSize)
  );
  const composerSize = await page.getByLabel("AI 질문").evaluate(
    (element) => Number.parseFloat(getComputedStyle(element).fontSize)
  );

  expect(promptSize).toBeGreaterThanOrEqual(12);
  expect(composerSize).toBeGreaterThanOrEqual(13);
});

test("completed inspection removes the empty prompt and groups findings", async ({ page }) => {
  await mockInspection(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Run agents" }).click();

  await expect(page.locator(".conversation-empty")).toHaveCount(0);
  await expect(page.locator(".tool-step").first()).toContainText("PLANNED");

  await page.getByRole("tab", { name: /Findings/ }).click();
  await expect(page.locator(".finding-group")).toHaveCount(2);
  await expect(page.locator(".finding-row")).toHaveCount(0);

  await page.getByRole("button", { name: /LWPOLYLINE.*1/ }).click();
  await expect(page.locator(".finding-row")).toHaveCount(1);
  await expect(page.locator(".finding-row")).toContainText("handle 239");
});

test("layer visibility reports visible and total model entities", async ({ page }) => {
  await page.goto("/");
  await page.locator(".layer-visibility-button").first().click();

  await expect(page.locator(".viewer-status")).toContainText("0 visible / 22 total");
});

test("project and session navigation keep independent scroll containers", async ({ page }) => {
  await page.goto("/");

  const search = page.getByLabel("Search workspace");
  const projectScroll = page.locator(".project-navigation-scroll");
  await expect(search).toBeVisible();
  await expect(projectScroll).toHaveCSS("overflow-y", "auto");
  await page.getByRole("tab", { name: "Sessions" }).click();
  const sessionScroll = page.locator(".session-navigation-scroll");
  await expect(sessionScroll).toHaveCSS("overflow-y", "auto");
  await expect(projectScroll).toHaveCount(0);
  await expect(search).toBeVisible();
});

test("keeps CAD controls inside the artifact instead of the global header", async ({ page }) => {
  await page.goto("/");

  const topbar = page.locator(".topbar");
  const artifact = page.getByRole("region", { name: "CAD 아티팩트" });
  await expect(topbar.getByText("Indexed", { exact: true })).toHaveCount(0);
  await expect(topbar.getByRole("button", { name: "Run agents" })).toHaveCount(0);
  await expect(topbar.getByLabel("전체 도면 검색")).toHaveCount(0);
  await expect(artifact.locator(".artifact-header").getByText("Indexed", { exact: true })).toBeVisible();
  await expect(artifact.getByRole("button", { name: "Run agents" })).toBeVisible();
  await expect(artifact.getByLabel("전체 도면 검색")).toBeVisible();
});

test("closes and restores the desktop artifact while expanding chat", async ({ page }) => {
  await page.goto("/");
  const conversation = page.getByRole("main", { name: "대화" });
  const before = await conversation.boundingBox();

  await page.getByRole("button", { name: "CAD 아티팩트 닫기" }).click();
  await expect(page.getByRole("region", { name: "CAD 아티팩트" })).toHaveCount(0);
  const expanded = await conversation.boundingBox();
  expect(expanded!.width).toBeGreaterThan(before!.width);

  await page.getByRole("button", { name: "CAD 아티팩트 열기" }).click();
  await expect(page.getByRole("region", { name: "CAD 아티팩트" })).toBeVisible();
});

test("offers Claude-like artifact version, copy, and download controls", async ({ page }) => {
  await page.goto("/");
  const artifact = page.getByRole("region", { name: "CAD 아티팩트" });

  await expect(artifact.getByLabel("아티팩트 버전")).toHaveValue("cad-index/v0.2");
  await expect(artifact.getByRole("button", { name: "아티팩트 복사" })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await artifact.getByRole("button", { name: "아티팩트 다운로드" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("export_sample.index.json");
});

test("uses Claude-style sidebar hierarchy and wider default chat", async ({ page }) => {
  await page.goto("/");

  const sidebar = page.getByLabel("Workspace navigation");
  await expect(sidebar.getByLabel("Search workspace")).toBeVisible();
  await expect(sidebar.getByRole("tab", { name: "Project", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(sidebar.getByRole("tab", { name: "Sessions", exact: true })).toBeVisible();
  await expect(sidebar.getByRole("tab", { name: "Skills", exact: true })).toBeVisible();
  await expect(sidebar.getByRole("tree", { name: "Drawing hierarchy" })).toBeVisible();

  const conversation = await page.getByRole("main", { name: "대화" }).boundingBox();
  expect(conversation!.width).toBeGreaterThanOrEqual(500);
  await expect(page.getByText("export_sample.dwg", { exact: true })).toHaveCount(2);
});

test("preserves a 500px conversation when restoring an older wide artifact", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("dwg.workspace-preferences.v1", JSON.stringify({
      theme: "system",
      artifactWidth: 760,
      sidebarSections: {
        project: true,
        drawing: true,
        sessions: true
      }
    }));
  });
  await page.goto("/");

  const conversation = await page.getByRole("main", { name: "대화" }).boundingBox();
  expect(conversation!.width).toBeGreaterThanOrEqual(500);
});

test("loads with in-memory defaults when browser storage access is blocked", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("blocked", "SecurityError");
      }
    });
  });

  await page.goto("/");

  await expect(page.getByRole("main", { name: "대화" })).toBeVisible();
  await expect(page.getByText("export_sample.dwg", { exact: true }).first()).toBeVisible();
});

test("migrates sidebar defaults from v1 and persists the v2 preference after reload", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("dwg.workspace-preferences.v1", JSON.stringify({
      theme: "system",
      artifactWidth: 680,
      sidebarSections: { project: true, drawing: true, sessions: true }
    }));
  });
  await page.goto("/");

  const resizer = page.getByRole("separator", { name: "Sidebar width" });
  await expect(resizer).toHaveAttribute("aria-valuenow", "320");
  await expect(resizer).toHaveAttribute("aria-valuemin", "280");
  await expect(resizer).toHaveAttribute("aria-valuemax", "420");
  await expect(resizer).toHaveAttribute("aria-orientation", "vertical");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("dwg.workspace-preferences.v2"))).not.toBeNull();

  await page.reload();
  await expect(resizer).toHaveAttribute("aria-valuenow", "320");
});

test("sidebar resizer uses 16px keyboard steps and clamps pointer resize at both bounds", async ({ page }) => {
  await page.goto("/");
  const resizer = page.getByRole("separator", { name: "Sidebar width" });

  await resizer.press("ArrowRight");
  await expect(resizer).toHaveAttribute("aria-valuenow", "336");
  await resizer.press("End");
  await expect(resizer).toHaveAttribute("aria-valuenow", "420");
  await resizer.press("Home");
  await expect(resizer).toHaveAttribute("aria-valuenow", "280");

  const box = await resizer.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(1000, box!.y + box!.height / 2);
  await page.mouse.up();
  await expect(resizer).toHaveAttribute("aria-valuenow", "420");

  const maxBox = await resizer.boundingBox();
  await page.mouse.move(maxBox!.x + maxBox!.width / 2, maxBox!.y + maxBox!.height / 2);
  await page.mouse.down();
  await page.mouse.move(0, maxBox!.y + maxBox!.height / 2);
  await page.mouse.up();
  await expect(resizer).toHaveAttribute("aria-valuenow", "280");
});

test("pointer cancellation clears resize state and permits a later pointer resize", async ({ page }) => {
  await page.goto("/");
  const resizer = page.getByRole("separator", { name: "Sidebar width" });
  const first = await beginPointerResize(page, resizer);

  await resizer.dispatchEvent("pointercancel", {
    bubbles: true,
    clientX: first.x,
    pointerId: first.pointerId
  });
  await expect(page.locator("body")).not.toHaveClass(/resizing-sidebar/);
  await page.mouse.move(first.x + 80, first.y);
  await page.mouse.up();
  await expect(resizer).toHaveAttribute("aria-valuenow", "320");

  await resizeSidebarWithPointer(page, resizer, 32);
  await expect(resizer).toHaveAttribute("aria-valuenow", "352");
});

test("lost capture and window blur clean resize state without stale width commits", async ({ page }) => {
  await page.goto("/");
  const resizer = page.getByRole("separator", { name: "Sidebar width" });
  const lost = await beginPointerResize(page, resizer);

  await expect.poll(() => resizer.evaluate(
    (element, pointerId) => element.hasPointerCapture(pointerId),
    lost.pointerId
  )).toBe(true);
  await resizer.dispatchEvent("lostpointercapture", {
    pointerId: lost.pointerId
  });
  await expect(page.locator("body")).not.toHaveClass(/resizing-sidebar/);
  expect(await resizer.evaluate(
    (element, pointerId) => element.hasPointerCapture(pointerId),
    lost.pointerId
  )).toBe(false);
  await page.mouse.move(lost.x + 80, lost.y);
  await page.mouse.up();
  await expect(resizer).toHaveAttribute("aria-valuenow", "320");

  const blurred = await beginPointerResize(page, resizer);
  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect(page.locator("body")).not.toHaveClass(/resizing-sidebar/);
  await page.mouse.move(blurred.x + 80, blurred.y);
  await page.mouse.up();
  await expect(resizer).toHaveAttribute("aria-valuenow", "320");

  await resizeSidebarWithPointer(page, resizer, 16);
  await expect(resizer).toHaveAttribute("aria-valuenow", "336");
});

test("invalid v2 sidebar storage falls back to usable defaults", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("dwg.workspace-preferences.v2", JSON.stringify({
      theme: "system",
      artifactWidth: 680,
      sidebarWidth: 320,
      sidebarTab: "not-a-tab",
      sidebarSections: { project: true, drawing: true, sessions: true }
    }));
  });
  await page.goto("/");

  await expect(page.getByRole("separator", { name: "Sidebar width" })).toHaveAttribute(
    "aria-valuenow",
    "320"
  );
});

test("contains clipboard permission failures without an unhandled rejection", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        async writeText() {
          throw new DOMException("denied", "NotAllowedError");
        }
      }
    });
  });
  await page.goto("/");

  await page.getByRole("button", { name: "아티팩트 복사" }).click();
  await page.waitForTimeout(50);

  expect(pageErrors).toEqual([]);
});

async function mockInspection(page: Page) {
  await page.route("**/api/inspections", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        status: "completed",
        drawingId: "dwg:test",
        events: [
          { sequence: 1, agentId: "orchestrator", action: "plan", status: "planned" },
          { sequence: 2, agentId: "drawing-index-agent", action: "build-index", status: "completed" },
          { sequence: 3, agentId: "orchestrator", action: "complete", status: "completed" }
        ],
        findings: [
          {
            id: "h:239",
            handle: "239",
            type: "LWPOLYLINE",
            layer: "0",
            bbox: { min: [0, 0, 0], max: [10, 10, 0] },
            reason: "layer:0",
            confidence: 1
          },
          {
            id: "h:23A",
            handle: "23A",
            type: "LINE",
            layer: "0",
            bbox: { min: [0, 0, 0], max: [10, 10, 0] },
            reason: "layer:0",
            confidence: 1
          }
        ],
        issues: [],
        warnings: []
      })
    })
  );
}

async function beginPointerResize(page: Page, resizer: Locator) {
  const box = await resizer.boundingBox();
  expect(box).not.toBeNull();
  await resizer.evaluate((element) => {
    element.addEventListener("pointerdown", (event) => {
      element.setAttribute("data-test-pointer-id", String(event.pointerId));
    }, { once: true });
  });
  const x = box!.x + box!.width / 2;
  const y = box!.y + box!.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  const pointerIdAttribute = await resizer.getAttribute("data-test-pointer-id");
  expect(pointerIdAttribute).not.toBeNull();
  const pointerId = Number(pointerIdAttribute);
  expect(Number.isFinite(pointerId)).toBe(true);
  return { pointerId, x, y };
}

async function resizeSidebarWithPointer(page: Page, resizer: Locator, delta: number) {
  const start = await beginPointerResize(page, resizer);
  await page.mouse.move(start.x + delta, start.y);
  await page.mouse.up();
}
