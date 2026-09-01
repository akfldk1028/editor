import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";
import { createCadGatewayServer } from "../../../../modules/cad-runtime/src/http/gateway.js";

const fixturePath = fileURLToPath(new URL("../../../../tests/fixtures/dwg/export_sample.dwg", import.meta.url));
let isolatedGateway: Awaited<ReturnType<typeof createCadGatewayServer>> | null = null;

test.afterEach(async () => {
  if (!isolatedGateway) return;
  await new Promise<void>((resolve) => isolatedGateway!.close(() => resolve()));
  isolatedGateway = null;
});

test("the real gateway and workspace render apply undo redo from one in-memory snapshot without changing source", async ({ page }) => {
  const gateway = isolatedGateway = await createCadGatewayServer({ workspaceRoot: fileURLToPath(new URL("../../../../", import.meta.url)) });
  await new Promise<void>((resolve) => gateway.listen(0, "127.0.0.1", resolve));
  const address = gateway.address();
  if (!address || typeof address === "string") throw new Error("Isolated edit gateway did not expose a TCP address.");
  const probe = await fetch(`http://127.0.0.1:${address.port}/api/drawing`);
  expect(probe.status).toBe(200);
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const target = new URL(route.request().url());
    target.port = String(address.port);
    const request = route.request();
    const headers = new Headers(request.headers());
    headers.delete("host");
    headers.delete("content-length");
    const response = await fetch(target, {
      method: request.method(),
      headers,
      body: ["GET", "HEAD"].includes(request.method()) ? undefined : request.postDataBuffer()
    });
    await route.fulfill({
      status: response.status,
      contentType: response.headers.get("content-type") ?? "application/json",
      body: Buffer.from(await response.arrayBuffer())
    });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  const sourceHash = sha256(await readFile(fixturePath));
  await page.goto("/");
  const beforePath = await page.locator('[data-handle="239"]').getAttribute("d");

  await page.getByRole("button", { name: "Run agents" }).click();
  await page.getByRole("tab", { name: /Findings/ }).click();
  const revisedFinding = page.locator(".finding-row").filter({ hasText: "handle 239" });
  if (!await revisedFinding.isVisible()) {
    await page.locator(".finding-group-heading").filter({ hasText: "LWPOLYLINE" }).click();
  }
  await revisedFinding.click();
  await page.getByRole("tab", { name: "Changes" }).click();
  await page.getByLabel("Move X").fill("5");
  await page.getByRole("button", { name: "Preview move" }).click();
  await page.getByRole("button", { name: "Approve changes" }).click();
  await expect(page.getByRole("status")).toContainText("Applied at revision 1");

  await expectSnapshot(page, [5, 0, 0], [105, 100, 0], 1);
  await expect(page.locator('[data-handle="239"]')).not.toHaveAttribute("d", beforePath ?? "");
  await page.getByRole("button", { name: "Run agents" }).click();
  await page.getByRole("tab", { name: /Findings/ }).click();
  if (!await revisedFinding.isVisible()) {
    await page.locator(".finding-group-heading").filter({ hasText: "LWPOLYLINE" }).click();
  }
  await revisedFinding.click();
  await page.getByRole("tab", { name: "Evidence" }).click();
  await expect(page.getByTestId("evidence-card")).toContainText("[5,0,0]");
  await expect(page.getByTestId("evidence-card")).toContainText("REVISION");
  expect(sha256(await readFile(fixturePath))).toBe(sourceHash);

  await page.getByRole("tab", { name: "Changes" }).click();
  await page.getByRole("button", { name: "Undo changes" }).click();
  await expect(page.getByRole("status")).toContainText("Undone at revision 2");
  await expectSnapshot(page, [0, 0, 0], [100, 100, 0], 2);
  await page.getByRole("tab", { name: "Changes" }).click();
  await page.getByRole("button", { name: "Redo changes" }).click();
  await expect(page.getByRole("status")).toContainText("Redone at revision 3");
  await expectSnapshot(page, [5, 0, 0], [105, 100, 0], 3);
  expect(sha256(await readFile(fixturePath))).toBe(sourceHash);
});

async function expectSnapshot(page: Page, min: number[], max: number[], revision: number) {
  const drawing = await page.evaluate(async () => (await fetch("/api/drawing")).json()) as {
    drawing?: { revision?: number };
    entities: Array<{ handle: string | null; bbox: { min: number[]; max: number[] } | null }>;
  };
  const entity = drawing.entities.find((candidate) => candidate.handle === "239");
  expect(entity?.bbox).toEqual({ min, max });
  expect(drawing.drawing?.revision).toBe(revision);
  await page.getByRole("tab", { name: "CAD Preview" }).click();
  await expect(page.locator(".viewer-status")).toContainText(`Revision ${revision}`);
  await expect(page.locator(".project-navigation-footer")).toContainText(`Revision ${revision}`);
}

function sha256(value: Buffer) {
  return createHash("sha256").update(value).digest("hex");
}
