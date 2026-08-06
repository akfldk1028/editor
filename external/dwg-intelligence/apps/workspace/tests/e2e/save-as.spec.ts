import { expect, test } from "@playwright/test";
import {
  parseCadDrawingExportResponse,
  parseCadVerificationResponse
} from "@dwg/contracts";

test("saves a verified drawing copy and downloads a report", async ({ page }, testInfo) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Export", exact: true }).click();
  await page.getByRole("button", { name: "Choose destination" }).click();
  await page.getByLabel("Base filename").fill("verified-copy");
  await page.getByRole("button", { name: "Save As DWG" }).click();
  await expect(page.getByRole("status")).toContainText("Verified");
  await expect(page.getByText("Destination grant used — choose again for another copy")).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("save-verified.png"),
    fullPage: true
  });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download JSON report" }).click();
  expect((await downloadPromise).suggestedFilename()).toMatch(/\.json$/u);
  await expect(page.getByRole("status")).toContainText("Report ready");
  await page.screenshot({
    path: testInfo.outputPath("export-report.png"),
    fullPage: true
  });
});

test("saves a verified DXF copy from a DWG source", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Export", exact: true }).click();
  const dxf = page.getByRole("button", { name: "Save As DXF" });
  await expect(dxf).toBeDisabled();

  await page.getByRole("button", { name: "Choose destination" }).click();
  await page.getByLabel("Base filename").fill("verified-dxf-copy");
  await expect(dxf).toBeEnabled();
  const saveResponse = page.waitForResponse((response) =>
    response.request().method() === "POST"
    && response.url().endsWith("/api/export/drawings")
  );
  await dxf.click();

  const saved = parseCadDrawingExportResponse(await (await saveResponse).json());
  await expect(page.getByRole("status")).toContainText("Verified");
  const verificationResponse = await page.request.get(
    `/api/export/verifications/${saved.verificationId}`
  );
  expect(verificationResponse.status()).toBe(200);
  const { verification } = parseCadVerificationResponse(
    await verificationResponse.json()
  );
  expect(verification.status).toBe("passed");
  expect(verification.format).toBe("dxf");
});
