import type { CadReportInput } from "./index.js";
import { canonicalReport, stableJson } from "./index.js";
import { BoundedTextWriter } from "./textWriter.js";

export function createJsonReport(input: CadReportInput): string {
  const writer = new BoundedTextWriter();
  writer.append(stableJson(canonicalReport(input)));
  writer.append("\n");
  return writer.finish();
}
