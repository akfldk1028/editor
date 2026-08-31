import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { types as nodeTypes } from "node:util";

import type {
  CadChange,
  CadOutputVerification,
  InspectionRun,
  ReportFormat
} from "@dwg/contracts";
import type { CadDocumentSnapshot } from "@dwg/cad-document";

import { createCsvReport } from "./csvReport.js";
import { createJsonReport } from "./jsonReport.js";
import { createPdfReport } from "./pdfReport.js";
import { createSvgReport } from "./svgReport.js";
import { BoundedTextWriter, MAX_REPORT_BYTES } from "./textWriter.js";

export { MAX_REPORT_BYTES } from "./textWriter.js";
export const MAX_REPORT_INPUT_DEPTH = 32;
export const MAX_REPORT_INPUT_COLLECTION_ITEMS = 20_000;
export const MAX_REPORT_INPUT_TOTAL_ITEMS = 100_000;
export const MAX_REPORT_INPUT_STRING_BYTES = 524_288;

/** Internal application input; it is deliberately not a @dwg/contracts DTO. */
export interface CadReportInput {
  document: CadDocumentSnapshot;
  findings: InspectionRun | null;
  changeSet: CadReportChangeSet | null;
  verification: CadOutputVerification | null;
}

export interface CadReportChangeSet {
  documentId: string;
  revision: number;
  transactionIds: string[];
  changes: CadChange[];
}

export interface ExportedReport {
  format: ReportFormat;
  mediaType: string;
  filename: string;
  bytes: Uint8Array;
  sha256: string;
}

export async function exportCadReport(
  input: CadReportInput,
  format: ReportFormat
): Promise<ExportedReport> {
  preflightReportInput(input);
  const body = createReportBody(input, format);
  const bytes = encodeBounded(body);
  return {
    format,
    mediaType: mediaTypeFor(format),
    filename: reportFilename(input.document, format),
    bytes,
    sha256: sha256(bytes)
  };
}

export function canonicalReport(input: CadReportInput): Record<string, unknown> {
  return canonicalize({
    document: input.document,
    findings: input.findings,
    changeSet: input.changeSet,
    verification: input.verification
  }, []) as Record<string, unknown>;
}

export function stableJson(value: unknown): string {
  const writer = new BoundedTextWriter();
  writeStableJson(writer, canonicalize(value, []));
  return writer.finish();
}

export function encodeBounded(text: string): Uint8Array {
  const bytes = new TextEncoder().encode(text);
  if (bytes.byteLength > MAX_REPORT_BYTES) {
    throw new Error("EXPORT_REPORT_BYTE_LIMIT");
  }
  return bytes;
}

export function reportLines(input: CadReportInput): string[] {
  const report = canonicalReport(input);
  return stableJson(report).match(/.{1,120}/gu) ?? ["{}"];
}

function createReportBody(input: CadReportInput, format: ReportFormat): string {
  switch (format) {
    case "json": return createJsonReport(input);
    case "csv": return createCsvReport(input);
    case "pdf": return createPdfReport(input);
    case "svg": return createSvgReport(input);
  }
}

function mediaTypeFor(format: ReportFormat): string {
  switch (format) {
    case "json": return "application/json; charset=utf-8";
    case "csv": return "text/csv; charset=utf-8";
    case "pdf": return "application/pdf";
    case "svg": return "image/svg+xml; charset=utf-8";
  }
}

function reportFilename(document: CadDocumentSnapshot, format: ReportFormat): string {
  const source = document.index.source.displayName.replace(/\.[^.]+$/u, "");
  const stem = source
    .normalize("NFKC")
    .replace(/[<>:"/\\|?*\u0000-\u001f]+/gu, "-")
    .replace(/[^\p{L}\p{N}._-]+/gu, "-")
    .replace(/-+/gu, "-")
    .replace(/^[-._]+|[-._]+$/gu, "")
    .slice(0, 96) || "drawing";
  return `${stem}-rev-${document.revision}-report.${format}`;
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex").toUpperCase();
}

function canonicalize(value: unknown, path: readonly string[]): unknown {
  if (Array.isArray(value)) {
    assertStandardArrayPrototype(value);
    const items: unknown[] = [];
    for (let index = 0; index < value.length; index += 1) {
      items[items.length] = canonicalize(value[index], [...path, "[]"]);
    }
    const collection = path.length > 0 ? path[path.length - 1] : undefined;
    if (collection !== undefined && unorderedCollections.has(collection)) {
      arraySort(
        items,
        (left, right) => compareText(collectionKey(collection, left), collectionKey(collection, right))
      );
    }
    return items;
  }
  if (!value || typeof value !== "object") return value;
  const entries = Object.entries(value as Record<string, unknown>);
  arraySort(entries, ([left], [right]) => compareText(left, right));
  const resultEntries: Array<[string, unknown]> = [];
  for (let index = 0; index < entries.length; index += 1) {
    const [key, item] = entries[index]!;
    resultEntries[resultEntries.length] = [key, canonicalize(item, [...path, key])];
  }
  return Object.fromEntries(resultEntries);
}

function collectionKey(collection: string, value: unknown): string {
  const object = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
  const fields = collectionSortFields[collection] ?? [];
  let explicit = object === null ? scalarKey(value) : "";
  if (object !== null) {
    for (let index = 0; index < fields.length; index += 1) {
      if (index > 0) explicit += "\u0000";
      explicit += scalarKey(object[fields[index]!]);
    }
  }
  return `${explicit}\u0000${stableSortKey(value)}`;
}

function scalarKey(value: unknown): string {
  if (value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return stableSortKey(value);
}

function stableSortKey(value: unknown): string {
  const writer = new BoundedTextWriter();
  writeStableJson(writer, value);
  return writer.finish();
}

function writeStableJson(writer: BoundedTextWriter, value: unknown): void {
  if (value === null) {
    writer.append("null");
  } else if (typeof value === "string") {
    writeJsonString(writer, value);
  } else if (typeof value === "number") {
    writer.append(Number.isFinite(value) ? String(value) : "null");
  } else if (typeof value === "boolean") {
    writer.append(value ? "true" : "false");
  } else if (Array.isArray(value)) {
    assertStandardArrayPrototype(value);
    writer.append("[");
    for (let index = 0; index < value.length; index += 1) {
      if (index > 0) writer.append(",");
      writeStableJson(writer, value[index]);
    }
    writer.append("]");
  } else if (value && typeof value === "object") {
    writer.append("{");
    const entries = Object.entries(value as Record<string, unknown>);
    for (let index = 0; index < entries.length; index += 1) {
      const [key, item] = entries[index]!;
      if (index > 0) writer.append(",");
      writeJsonString(writer, key);
      writer.append(":");
      writeStableJson(writer, item);
    }
    writer.append("}");
  } else {
    writer.append("null");
  }
}

function writeJsonString(writer: BoundedTextWriter, value: string): void {
  writer.append('"');
  let run = "";
  const flush = () => {
    if (run.length > 0) writer.append(run);
    run = "";
  };
  for (const character of value) {
    const codePoint = character.codePointAt(0)!;
    if (character === '"' || character === "\\") {
      flush();
      writer.append(`\\${character}`);
    } else if (codePoint <= 0x1f) {
      flush();
      writer.append(`\\u${codePoint.toString(16).padStart(4, "0")}`);
    } else {
      run += character;
      if (run.length >= 4_096) flush();
    }
  }
  flush();
  writer.append('"');
}

function preflightReportInput(input: CadReportInput): void {
  const active = new WeakSet<object>();
  const stack: PreflightFrame[] = [{ kind: "enter", value: input, depth: 0 }];
  let collectionItems = 0;
  let estimatedBytes = 0;

  while (stack.length > 0) {
    const current = stack[stack.length - 1]!;
    stack.length -= 1;
    if (current.kind === "exit") {
      active.delete(current.value);
      continue;
    }
    if (current.depth > MAX_REPORT_INPUT_DEPTH) {
      throw new Error("EXPORT_REPORT_INPUT_DEPTH_LIMIT");
    }
    const value = current.value;
    if (typeof value === "string") {
      assertWellFormedUtf16(value);
      const bytes = Buffer.byteLength(value, "utf8");
      if (bytes > MAX_REPORT_INPUT_STRING_BYTES) {
        throw new Error("EXPORT_REPORT_INPUT_STRING_LIMIT EXPORT_REPORT_BYTE_LIMIT");
      }
      estimatedBytes += bytes;
    } else if (value && typeof value === "object") {
      if (nodeTypes.isProxy(value)) throw new Error("EXPORT_REPORT_INPUT_PROXY");
      const isArray = Array.isArray(value);
      if (isArray) assertStandardArrayPrototype(value);
      if (active.has(value)) throw new Error("EXPORT_REPORT_INPUT_CYCLE");
      active.add(value);
      stack[stack.length] = { kind: "exit", value };
      if (isArray) {
        if (!Number.isSafeInteger(value.length) || value.length > MAX_REPORT_INPUT_COLLECTION_ITEMS) {
          throw new Error("EXPORT_REPORT_INPUT_COLLECTION_LIMIT");
        }
        collectionItems += value.length;
        if (collectionItems > MAX_REPORT_INPUT_TOTAL_ITEMS) {
          throw new Error("EXPORT_REPORT_INPUT_COLLECTION_LIMIT");
        }
        rejectArrayProperties(value);
        for (let index = value.length - 1; index >= 0; index -= 1) {
          const key = String(index);
          const descriptor = Object.getOwnPropertyDescriptor(value, key);
          if (descriptor === undefined) throw new Error("EXPORT_REPORT_INPUT_ARRAY_SPARSE");
          if (!("value" in descriptor)) throw new Error("EXPORT_REPORT_INPUT_ACCESSOR");
          if (!descriptor.enumerable) throw new Error("EXPORT_REPORT_INPUT_ARRAY_PROPERTY");
          estimatedBytes += Buffer.byteLength(key, "utf8");
          stack[stack.length] = {
            kind: "enter",
            value: descriptor.value,
            depth: current.depth + 1
          };
        }
      } else {
        const prototype = Object.getPrototypeOf(value);
        if (prototype !== Object.prototype && prototype !== null) {
          throw new Error("EXPORT_REPORT_INPUT_PROTOTYPE");
        }
        let ownItems = 0;
        for (const key in value) {
          if (!Object.hasOwn(value, key)) continue;
          ownItems += 1;
          collectionItems += 1;
          if (
            ownItems > MAX_REPORT_INPUT_COLLECTION_ITEMS ||
            collectionItems > MAX_REPORT_INPUT_TOTAL_ITEMS
          ) {
            throw new Error("EXPORT_REPORT_INPUT_COLLECTION_LIMIT");
          }
          assertWellFormedUtf16(key);
          const descriptor = Object.getOwnPropertyDescriptor(value, key)!;
          if (!("value" in descriptor)) throw new Error("EXPORT_REPORT_INPUT_ACCESSOR");
          estimatedBytes += Buffer.byteLength(key, "utf8");
          stack[stack.length] = {
            kind: "enter",
            value: descriptor.value,
            depth: current.depth + 1
          };
        }
      }
    } else {
      estimatedBytes += 16;
    }
    if (estimatedBytes > MAX_REPORT_BYTES) {
      throw new Error("EXPORT_REPORT_INPUT_BYTE_LIMIT EXPORT_REPORT_BYTE_LIMIT");
    }
  }
}

function rejectArrayProperties(value: unknown[]): void {
  const keys = Object.keys(value);
  for (let index = 0; index < keys.length; index += 1) {
    const key = keys[index]!;
    if (!isArrayIndexKey(key, value.length)) {
      throw new Error("EXPORT_REPORT_INPUT_ARRAY_PROPERTY");
    }
  }
}

function assertStandardArrayPrototype(value: unknown[]): void {
  if (Object.getPrototypeOf(value) !== Array.prototype) {
    throw new Error("EXPORT_REPORT_INPUT_PROTOTYPE");
  }
}

function isArrayIndexKey(key: string, length: number): boolean {
  const index = Number(key);
  return Number.isSafeInteger(index) && index >= 0 && index < length && String(index) === key;
}

function assertWellFormedUtf16(value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        throw new Error("EXPORT_REPORT_INPUT_UTF16_INVALID");
      }
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      throw new Error("EXPORT_REPORT_INPUT_UTF16_INVALID");
    }
  }
}

type PreflightFrame =
  | { kind: "enter"; value: unknown; depth: number }
  | { kind: "exit"; value: object };

const unorderedCollections = new Set([
  "entities",
  "layers",
  "layouts",
  "linetypes",
  "unsupported",
  "warnings",
  "findings",
  "issues",
  "missing",
  "evidence"
]);

const collectionSortFields: Record<string, readonly string[]> = {
  entities: ["id", "handle", "type", "layer", "layout"],
  layers: ["id", "name"],
  layouts: ["id", "name"],
  linetypes: ["id", "name"],
  unsupported: ["type", "reason", "count"],
  findings: ["id", "handle", "type", "layer", "reason"],
  issues: ["entityId"],
  evidence: ["id", "handle", "type", "layer"]
};

const arraySort = Function.prototype.call.bind(Array.prototype.sort) as <T>(
  value: T[],
  compare?: (left: T, right: T) => number
) => T[];

export function compareText(left: string, right: string): number {
  return Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"));
}
