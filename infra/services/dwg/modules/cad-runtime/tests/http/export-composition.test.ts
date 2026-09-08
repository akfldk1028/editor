import assert from "node:assert/strict";
import test from "node:test";

import {
  parseCadDrawingExportResponse,
  parseCadReportExportResponse,
  parseDestinationGrantResponse
} from "@dwg/contracts";

import { createCadApplication } from "../../src/application/createCadApplication.js";

test("assembled application exposes shared save and report capabilities", async () => {
  const application = await createCadApplication();
  assert.deepEqual(application.capabilityNames.slice(-3), [
    "export.report",
    "export.drawing",
    "verification.get"
  ]);
});

test("public export responses are strict and path free", () => {
  assert.equal(parseDestinationGrantResponse({
    grantId: "11111111-1111-4111-8111-111111111111",
    displayDirectory: "Exports",
    expiresAt: 1
  }).displayDirectory, "Exports");
  assert.equal(parseCadReportExportResponse({
    downloadId: "11111111-1111-4111-8111-111111111111",
    filename: "drawing.json",
    mediaType: "application/json; charset=utf-8",
    sha256: "A".repeat(64)
  }).filename, "drawing.json");
  assert.equal(parseCadDrawingExportResponse({
    verificationId: "11111111-1111-4111-8111-111111111111",
    status: "passed"
  }).status, "passed");
  assert.throws(() => parseDestinationGrantResponse({
    grantId: "11111111-1111-4111-8111-111111111111",
    displayDirectory: "Exports",
    expiresAt: 1,
    path: "C:/outside"
  }));
});
