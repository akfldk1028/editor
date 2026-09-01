import type {
  ReportFormat
} from "@dwg/contracts";
import type {
  CadReportInput,
  exportCadReport
} from "@dwg/cad-export";

import {
  CadSaveError,
  type CadCapabilityModule,
  type CadCapabilityName,
  type CadSaveCoordinator,
  type CadSaveInput
} from "./contracts.js";

const names = [
  "export.report",
  "export.drawing",
  "verification.get"
] as const satisfies readonly CadCapabilityName[];

export function createSaveCapabilityModule(
  coordinator: CadSaveCoordinator,
  reportExporter: typeof exportCadReport
): CadCapabilityModule {
  return {
    names,
    async execute(name, input, signal) {
      if (signal?.aborted) throw abortError();
      switch (name) {
        case "export.drawing":
          return coordinator.saveCopy(parseDrawingInput(input), signal);
        case "verification.get":
          return coordinator.getVerification(parseVerificationInput(input));
        case "export.report": {
          const report = parseReportInput(input);
          return reportExporter(report.input, report.format);
        }
        default:
          throw new CadSaveError("CAD_SAVE_INPUT_INVALID");
      }
    }
  };
}

function parseDrawingInput(input: unknown): CadSaveInput {
  const value = strictRecord(input, [
    "documentId",
    "expectedRevision",
    "destinationGrantId",
    "baseFilename",
    "format",
    "version"
  ]);
  return value as unknown as CadSaveInput;
}

function parseVerificationInput(input: unknown): string {
  const value = strictRecord(input, ["id"]);
  if (typeof value.id !== "string" || value.id.length < 1 || value.id.length > 256) {
    throw new CadSaveError("CAD_SAVE_INPUT_INVALID");
  }
  return value.id;
}

function parseReportInput(input: unknown): {
  input: CadReportInput;
  format: ReportFormat;
} {
  const value = strictRecord(input, ["input", "format"]);
  if (
    !isPlainObject(value.input)
    || (
      value.format !== "json"
      && value.format !== "csv"
      && value.format !== "pdf"
      && value.format !== "svg"
    )
  ) {
    throw new CadSaveError("CAD_SAVE_INPUT_INVALID");
  }
  return {
    input: value.input as unknown as CadReportInput,
    format: value.format
  };
}

function strictRecord(
  input: unknown,
  expectedKeys: readonly string[]
): Record<string, unknown> {
  if (!isPlainObject(input)) {
    throw new CadSaveError("CAD_SAVE_INPUT_INVALID");
  }
  const keys = Object.keys(input).sort();
  const expected = [...expectedKeys].sort();
  if (
    keys.length !== expected.length
    || keys.some((key, index) => key !== expected[index])
  ) {
    throw new CadSaveError("CAD_SAVE_INPUT_INVALID");
  }
  return input;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}
