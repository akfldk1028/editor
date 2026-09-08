import { expect, test } from "@playwright/test";

const findingHandles = ["239", "23A", "23B", "23C", "23D"];

test("runs the real inspection API and renders returned evidence", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/providers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ providers: [] })
    })
  );
  const requests: unknown[] = [];
  await page.route("**/api/inspections", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        status: "completed",
        drawingId: "dwg:b60b4a7242e43b34ca35561b",
        events: [
          {
            sequence: 1,
            agentId: "orchestrator",
            action: "plan",
            status: "planned"
          },
          {
            sequence: 2,
            agentId: "drawing-index-agent",
            action: "build-index",
            status: "completed"
          },
          {
            sequence: 3,
            agentId: "search-agent",
            action: "search-layer",
            status: "completed"
          },
          {
            sequence: 4,
            agentId: "evidence-agent",
            action: "verify-evidence",
            status: "completed"
          },
          {
            sequence: 5,
            agentId: "orchestrator",
            action: "complete",
            status: "completed"
          }
        ],
        findings: findingHandles.map((handle) => ({
          id: `h:${handle}`,
          handle,
          type: handle === "239" ? "LWPOLYLINE" : "LINE",
          layer: "0",
          bbox: {
            min: [0, 0, 0],
            max: [10, 10, 0]
          },
          reason: "layer:0",
          confidence: 1
        })),
        issues: [],
        warnings: []
      })
    });
  });
  await page.goto("/");

  await page.getByRole("button", { name: "Run agents" }).click();

  await expect(page.getByText("5개 주요 객체")).toBeVisible();
  await expect(page.locator(".cad-entity.highlighted")).toHaveCount(5);
  await page.getByRole("tab", { name: /Findings/ }).click();
  await expect(page.locator(".finding-group")).toHaveCount(2);
  expect(requests).toEqual([
    { checks: [{ kind: "layer", value: "0" }] }
  ]);

  await page.getByRole("button", { name: /0 LWPOLYLINE 1개/ }).click();
  await page.locator(".finding-row").click();
  await expect(page.getByTestId("evidence-card")).toContainText("239");
  await page.getByRole("tab", { name: /CAD Preview/ }).click();
  await expect(page.locator('[data-handle="239"]')).toHaveClass(/highlighted/);

  await page.getByRole("button", { name: "검사 초기화" }).click();
  await expect(page.locator(".cad-entity.highlighted")).toHaveCount(0);
  await expect(page.getByText("VERIFIED RESULT")).toBeHidden();
});
