import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import {
  parseCadEditPreviewRequest,
  parseCadEditPreviewResponse,
  type CadEditBatch
} from "@dwg/contracts";
import {
  documentationCaptureDirectory,
  documentationCapturePath
} from "../support/repositoryOutputPaths.ts";

const captureDirectory = documentationCaptureDirectory;

test.describe.configure({ mode: "serial" });

test("captures the required navigation, change, narrow, and theme states through visible controls", async ({ page }) => {
  await mkdir(captureDirectory, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  await page.getByRole("tab", { name: "Skills", exact: true }).click();
  await expect(page.getByRole("region", { name: "Skills" })).toContainText("inspect-drawing");
  await stabilize(page);
  await capture(page, "skill-selected.png");

  await mockInspection(page);
  await page.route("**/api/edit/preview", (route) => {
    const batch = parseCadEditPreviewRequest(route.request().postDataJSON()).batch;
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(capturePreview(batch)) });
  });
  await page.reload();
  await createVisibleMoveProposal(page);
  await expect(page.getByRole("region", { name: "Change review" })).toContainText("Selected handle 239");
  await capture(page, "change-preview.png");

  await page.setViewportSize({ width: 1024, height: 768 });
  await page.reload();
  await page.getByRole("button", { name: "탐색 열기" }).click();
  await expect(page.getByRole("dialog", { name: "Workspace navigation" })).toHaveClass(/overlay/);
  await capture(page, "sidebar-narrow.png");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload();
  await page.getByRole("button", { name: "설정" }).click();
  await page.getByLabel("테마").selectOption("dark");
  await expect(page.locator(".app-shell")).toHaveAttribute("data-theme", "dark");
  await page.keyboard.press("Escape");
  await capture(page, "dark-theme.png");
});

test("captures the single workspace route in its key states", async ({ page }) => {
  await mkdir(captureDirectory, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockProviderStatus(page);
  await page.goto("/");
  await expect(page.getByText("export_sample.dwg", { exact: true }).first()).toBeVisible();
  await stabilize(page);
  await capture(page, "01-workspace-loaded.png");

  await page.getByRole("button", { name: "Run agents" }).click();
  await expect(page.getByText("VERIFIED RESULT")).toBeVisible();
  await page.getByRole("tab", { name: /Findings/ }).click();
  await capture(page, "02-inspection-complete.png");

  await page.getByRole("button", { name: "검사 초기화" }).click();
  await page.getByRole("tab", { name: /CAD Preview/ }).click();
  const layerToggle = page.locator(".layer-visibility-button").first();
  await layerToggle.click();
  await expect(layerToggle).toHaveAccessibleName("Show layer 0");
  await capture(page, "03-layer-hidden.png");

  await page.reload();
  await stabilize(page);
  const claudeButton = page.getByRole("button", { name: "Claude", exact: true });
  await expect(claudeButton).toBeEnabled();
  await claudeButton.click();
  await expect(claudeButton).toHaveClass(/active/);
  await page.getByLabel("AI 질문").fill("도면의 TEXT 객체를 근거와 함께 알려줘");
  await page.getByRole("button", { name: "전송" }).click();
  await expect(page.getByTestId("live-response")).toContainText("[handle:591]");
  await capture(page, "04-claude-selected.png");

  await page.getByRole("button", { name: "설정" }).click();
  await page.getByLabel("테마").selectOption("dark");
  await expect(page.getByTestId("cad-canvas")).toHaveCSS("background-color", "rgb(23, 26, 28)");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "뷰어 설정" })).toBeHidden();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await capture(page, "05-dark-theme.png");
});

test("renders a single overview contact sheet", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto(
    pathToFileURL(documentationCapturePath("index.html")).toString()
  );
  await expect(page.locator("img")).toHaveCount(4);
  await expect(page.locator("img").last()).toBeVisible();
  await page.evaluate(async () => {
    await Promise.all(
      [...document.images].map((image) => image.decode())
    );
  });
  await capture(page, "00-overview.png");
});

test("captures verified Save As and report download through visible controls", async ({ page }) => {
  await mkdir(captureDirectory, { recursive: true });
  await page.route("**/api/export/destination-grants", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      grantId: "11111111-1111-4111-8111-111111111111",
      displayDirectory: "Documentation exports",
      expiresAt: 4_102_444_800_000
    })
  }));
  await page.route("**/api/export/drawings", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      verificationId: "22222222-2222-4222-8222-222222222222",
      status: "passed"
    })
  }));
  await page.route("**/api/export/reports", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      downloadId: "33333333-3333-4333-8333-333333333333",
      filename: "export-sample-rev-0-report.json",
      mediaType: "application/json; charset=utf-8",
      sha256: "A".repeat(64)
    })
  }));
  await page.route("**/api/export/reports/33333333-3333-4333-8333-333333333333", (route) =>
    route.fulfill({
      contentType: "application/json; charset=utf-8",
      headers: { "content-disposition": 'attachment; filename="export-sample-rev-0-report.json"' },
      body: JSON.stringify({ documentId: "capture" })
    })
  );

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("tab", { name: "Export", exact: true }).click();
  await page.getByRole("button", { name: "Choose destination" }).click();
  await page.getByLabel("Base filename").fill("verified-copy");
  await page.getByRole("button", { name: "Save As DXF" }).click();
  await expect(page.getByRole("status")).toContainText("Verified");
  await expect(page.getByText("Destination grant used — choose again for another copy")).toBeVisible();
  await capture(page, "save-verified.png");

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download JSON report" }).click();
  expect((await download).suggestedFilename()).toBe("export-sample-rev-0-report.json");
  await expect(page.getByRole("status")).toContainText("export-sample-rev-0-report.json");
  await capture(page, "export-report.png");
});


test("captures the focused desktop sidebar preference state", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockProviderStatus(page);
  await page.goto("/");

  const resizer = page.getByRole("separator", { name: "Sidebar width" });
  await expect(resizer).toHaveAttribute("aria-valuenow", "320");
  await resizer.press("ArrowRight");
  await expect(resizer).toHaveAttribute("aria-valuenow", "336");
  await capture(page, "sidebar-preferences.png");
});

test("captures populated change review at desktop and narrow widths", async ({ page }) => {
  await mkdir(captureDirectory, { recursive: true });
  await mockInspection(page);
  await page.route("**/api/edit/preview", (route) => {
    const batch = parseCadEditPreviewRequest(route.request().postDataJSON()).batch;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(capturePreview(batch))
    });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await createVisibleMoveProposal(page);
  const review = page.getByRole("region", { name: "Change review" });
  await expect(review).toContainText("Selected handle 239");
  await expect(page.getByRole("button", { name: "Approve changes" })).toBeVisible();
  await stabilize(page);
  await capture(page, "change-review-desktop.png");

  await page.setViewportSize({ width: 800, height: 900 });
  await page.reload();
  await page.locator(".artifact-toggle").click();
  await createVisibleMoveProposal(page);
  await expect(review).toContainText("Selected handle 239");
  await page.getByRole("button", { name: "Approve changes" }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("button", { name: "Approve changes" })).toBeInViewport();
  await stabilize(page);
  await capture(page, "change-review-narrow.png");
});

async function mockProviderStatus(page: Page) {
  await page.route("**/api/providers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        providers: [
          {
            id: "codex",
            label: "GPT · Codex",
            installed: true,
            authenticated: true,
            authMethod: "chatgpt",
            detail: "기존 ChatGPT 로그인 세션"
          },
          {
            id: "claude",
            label: "Claude",
            installed: true,
            authenticated: true,
            authMethod: "claude.ai",
            subscription: "max",
            detail: "기존 Claude 로그인 세션 · max"
          }
        ]
      })
    })
  );
  await page.route("**/api/chat", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "claude",
        text: "TEXT Hello를 확인했습니다. [handle:591]",
        sessionId: "98d84d53-7861-4c73-a789-d6c8f5490966"
      })
    })
  );
}

async function stabilize(page: Page) {
  await page.addStyleTag({
    content:
      "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
  });
}

async function capture(page: Page, fileName: string) {
  await stabilize(page);
  await page.evaluate(async () => {
    await document.fonts.ready;
    (document.activeElement as HTMLElement | null)?.blur();
  });
  await page.screenshot({
    path: documentationCapturePath(fileName),
    fullPage: true,
    animations: "disabled"
  });
}

async function createVisibleMoveProposal(page: Page) {
  await page.getByRole("button", { name: "Run agents" }).click();
  await page.getByRole("tab", { name: /Findings/ }).click();
  await page.locator(".finding-group-heading").click();
  await page.locator(".finding-row").click();
  await page.getByRole("tab", { name: "Changes" }).click();
  await page.getByLabel("Move X").fill("5");
  await page.getByRole("button", { name: "Preview move" }).click();
  await expect(page.getByRole("status")).toContainText("Ready for approval");
}

function capturePreview(batch: CadEditBatch) {
  return parseCadEditPreviewResponse({
    previewId: "10000000-0000-4000-8000-000000000001",
    documentId: batch.documentId,
    transactionId: batch.transactionId,
    baseRevision: batch.expectedRevision,
    nextRevision: batch.expectedRevision + 1,
    changeCount: 1,
    changesTruncated: false,
    changes: [
      {
        commandId: batch.commands[0]!.commandId,
        kind: "entity.move",
        targetId: "h:239",
        before: { id: "h:239", handle: "239", type: "LWPOLYLINE", layer: "0", bbox: { min: [0, 0, 0], max: [10, 10, 0] }, text: null },
        after: { id: "h:239", handle: "239", type: "LWPOLYLINE", layer: "0", bbox: { min: [5, 0, 0], max: [15, 10, 0] }, text: null }
      }
    ],
    warningCount: 0,
    warningsTruncated: false,
    warnings: []
  });
}

async function mockInspection(page: Page) {
  await page.route("**/api/inspections", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      status: "completed",
      drawingId: "dwg:b60b4a7242e43b34ca35561b",
      events: [],
      findings: [{
        id: "h:239",
        handle: "239",
        type: "LWPOLYLINE",
        layer: "0",
        bbox: { min: [0, 0, 0], max: [10, 10, 0] },
        reason: "layer:0",
        confidence: 1
      }],
      issues: [],
      warnings: []
    })
  }));
}
