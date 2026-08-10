import type { CadReportInput } from "./index.js";
import { canonicalReport } from "./index.js";
import { BoundedTextWriter } from "./textWriter.js";

export function createCsvReport(input: CadReportInput): string {
  const normalized = canonicalReport(input) as unknown as CadReportInput;
  const rows: string[][] = [["section", "id", "type", "layer", "text", "detail"]];
  const entities = normalized.document.index.entities;
  for (let index = 0; index < entities.length; index += 1) {
    const entity = entities[index]!;
    rows[rows.length] = ["entity", entity.id, entity.type, entity.layer, entity.text ?? "", geometryDetail(entity.geometry)];
  }
  const findings = normalized.findings?.findings ?? [];
  for (let index = 0; index < findings.length; index += 1) {
    const finding = findings[index]!;
    rows[rows.length] = ["finding", finding.id, finding.type, finding.layer, finding.text ?? "", finding.reason];
  }
  const warnings = normalized.findings?.warnings ?? [];
  for (let index = 0; index < warnings.length; index += 1) {
    rows[rows.length] = ["warning", "", "", "", warnings[index]!, ""];
  }
  const transactionIds = normalized.changeSet?.transactionIds ?? [];
  for (let index = 0; index < transactionIds.length; index += 1) {
    rows[rows.length] = ["transaction", transactionIds[index]!, "", "", "", ""];
  }
  const changes = normalized.changeSet?.changes ?? [];
  for (let index = 0; index < changes.length; index += 1) {
    const change = changes[index]!;
    rows[rows.length] = ["change", change.commandId, change.kind, "", "", change.targetId];
  }
  const writer = new BoundedTextWriter();
  writer.append("\uFEFF");
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex]!;
    if (rowIndex > 0) writer.append("\r\n");
    for (let cellIndex = 0; cellIndex < row.length; cellIndex += 1) {
      if (cellIndex > 0) writer.append(",");
      writer.append(csvCell(row[cellIndex]!));
    }
  }
  writer.append("\r\n");
  return writer.finish();
}

function geometryDetail(geometry: CadReportInput["document"]["index"]["entities"][number]["geometry"]): string {
  return geometry.kind === "line" ? "line" : `Unsupported geometry: ${geometry.kind === "unavailable" || geometry.kind === "bbox" ? geometry.reason : geometry.kind}`;
}

function csvCell(value: string): string {
  const literal = /^[\p{White_Space}\p{Cc}]*[=+\-@]/u.test(value) ? `'${value}` : value;
  return /[",\r\n]/u.test(literal) ? `"${literal.replaceAll('"', '""')}"` : literal;
}
