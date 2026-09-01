import assert from "node:assert/strict";
import test from "node:test";

import {
  parseExportCapabilitiesResponse,
  parseExportCapabilityItem,
  parseCadOutputVerification,
  type CadOutputVerification,
  type ExportCapabilityItem
} from "./export.js";

const exactCapabilities: ExportCapabilityItem[] = [
  { format: "json", kind: "report", available: false, reason: "EXPORT_MODULE_NOT_INSTALLED" },
  { format: "csv", kind: "report", available: false, reason: "EXPORT_MODULE_NOT_INSTALLED" },
  { format: "pdf", kind: "report", available: false, reason: "EXPORT_MODULE_NOT_INSTALLED" },
  { format: "svg", kind: "report", available: false, reason: "EXPORT_MODULE_NOT_INSTALLED" },
  { format: "dxf", kind: "drawing", available: false, reason: "EXPORT_MODULE_NOT_INSTALLED" },
  { format: "dwg", kind: "drawing", available: true, reason: null }
];

test("accepts exhaustive export capabilities with correlated availability reasons", () => {
  assert.deepEqual(
    parseExportCapabilitiesResponse({ capabilities: exactCapabilities }),
    { capabilities: exactCapabilities }
  );
});

test("rejects unavailable capabilities without a reason and available capabilities with a reason", () => {
  assert.throws(
    () => parseExportCapabilityItem({ format: "json", kind: "report", available: false, reason: null }),
    /EXPORT_CAPABILITY_ITEM_INVALID/
  );
  assert.throws(
    () => parseExportCapabilityItem({ format: "json", kind: "report", available: true, reason: "READY" }),
    /EXPORT_CAPABILITY_ITEM_INVALID/
  );
});

test("rejects empty and oversized unavailability reasons", () => {
  assert.throws(
    () => parseExportCapabilityItem({ format: "json", kind: "report", available: false, reason: "" }),
    /EXPORT_CAPABILITY_ITEM_INVALID/
  );
  assert.throws(
    () => parseExportCapabilityItem({ format: "json", kind: "report", available: false, reason: "X".repeat(129) }),
    /EXPORT_CAPABILITY_ITEM_INVALID/
  );
});

test("requires every exact export format once", () => {
  assert.throws(
    () => parseExportCapabilitiesResponse({ capabilities: exactCapabilities.slice(0, -1) }),
    /EXPORT_CAPABILITIES_RESPONSE_INVALID/
  );
  assert.throws(
    () => parseExportCapabilitiesResponse({
      capabilities: [...exactCapabilities.slice(0, -1), exactCapabilities[0]]
    }),
    /EXPORT_CAPABILITIES_RESPONSE_INVALID/
  );
});

test("parses only bounded, strict CAD output verification DTOs", () => {
  const valid: CadOutputVerification = {
    id: "verification:1",
    status: "passed",
    format: "dxf",
    version: "AC1032",
    sourceSha256: "a".repeat(64),
    outputSha256: "b".repeat(64),
    intendedChangeCount: 2,
    verifiedChangeCount: 2,
    copiedHandleMap: { "20": "120", "10": "110" },
    warnings: ["source copied"]
  };

  assert.deepEqual(parseCadOutputVerification(valid), {
    ...valid,
    sourceSha256: "A".repeat(64),
    outputSha256: "B".repeat(64),
    copiedHandleMap: { "10": "110", "20": "120" }
  });
  assert.throws(
    () => parseCadOutputVerification({ ...valid, unknown: true }),
    /CAD_OUTPUT_VERIFICATION_INVALID/
  );
  assert.throws(
    () => parseCadOutputVerification({ ...valid, warnings: ["x".repeat(513)] }),
    /CAD_OUTPUT_VERIFICATION_INVALID/
  );
  assert.throws(() => parseCadOutputVerification(null), /CAD_OUTPUT_VERIFICATION_INVALID/);
});
