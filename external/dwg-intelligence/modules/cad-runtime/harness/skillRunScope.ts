import type { CadCapabilityRuntime } from "@dwg/cad-capabilities";
import {
  MAX_SKILL_RELATED_DOCUMENT_IDS,
  type CadEntityIndex
} from "@dwg/contracts";

export interface CliDocumentScope {
  documentId: string;
  relatedDocumentIds: string[];
}

export async function resolveCliDocumentScope(
  input: unknown,
  declaredDocumentId: string | undefined,
  declaredRelatedDocumentIds: readonly string[],
  capabilities: CadCapabilityRuntime,
  signal?: AbortSignal
): Promise<CliDocumentScope> {
  assertDeclaredRelated(declaredRelatedDocumentIds);
  let documentId = declaredDocumentId;
  if (documentId === undefined && isRecord(input)) {
    if (validDocumentId(input.documentId)) {
      documentId = input.documentId;
    } else if (typeof input.path === "string") {
      const opened = await capabilities.execute("document.open", {
        path: input.path
      }, signal) as { drawingId?: unknown };
      if (validDocumentId(opened.drawingId)) documentId = opened.drawingId;
    }
  }
  if (!validDocumentId(documentId) || declaredRelatedDocumentIds.includes(documentId)) {
    throw new Error("DOCUMENT_SCOPE_REQUIRED");
  }
  return {
    documentId,
    relatedDocumentIds: [...declaredRelatedDocumentIds]
  };
}

export async function preloadCliComparisonScope(
  beforePath: string,
  afterPath: string,
  readIndex: (path: string, signal?: AbortSignal) => Promise<CadEntityIndex>,
  signal: AbortSignal
): Promise<CliDocumentScope> {
  const before = await readIndex(beforePath, signal);
  const after = await readIndex(afterPath, signal);
  if (
    !validDocumentId(before.drawingId) ||
    !validDocumentId(after.drawingId) ||
    before.drawingId === after.drawingId
  ) throw new Error("DOCUMENT_SCOPE_AMBIGUOUS");
  return {
    documentId: before.drawingId,
    relatedDocumentIds: [after.drawingId]
  };
}

function assertDeclaredRelated(values: readonly string[]): void {
  if (
    values.length > MAX_SKILL_RELATED_DOCUMENT_IDS ||
    !values.every(validDocumentId) ||
    new Set(values).size !== values.length
  ) throw new Error("DOCUMENT_SCOPE_INVALID");
}

function validDocumentId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 256 &&
    /^[A-Za-z0-9][A-Za-z0-9:._-]*$/.test(value)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
