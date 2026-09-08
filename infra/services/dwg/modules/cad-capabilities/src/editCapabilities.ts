import { randomUUID } from "node:crypto";

import {
  MAX_CAD_EDIT_PREVIEW_CHANGES,
  MAX_CAD_EDIT_PREVIEW_WARNINGS,
  parseCadEditApplyRequest,
  parseCadEditHistoryRequest,
  parseCadEditPreviewRequest,
  type CadEditApplyResponse,
  type CadEditHistoryRequest,
  type CadEditPreviewResponse
} from "@dwg/contracts";
import {
  CadEditError,
  type CadCommittedTransactionStore,
  type CadEditHistory
} from "@dwg/cad-edit";

import type { CadCapabilityModule, CadCapabilityName } from "./contracts.js";

const PREVIEW_TTL_MS = 10 * 60 * 1000;
const MAX_PREVIEWS_PER_DOCUMENT = 20;
const PREVIEW_TOMBSTONE_TTL_MS = 10 * 60 * 1000;
const MAX_PREVIEW_TOMBSTONES_PER_DOCUMENT = 40;

type PreviewStatus = "applied" | "rejected" | "stale" | "expired" | "evicted";

interface StoredPreview {
  documentId: string;
  createdAt: number;
  preview: ReturnType<CadEditHistory["preview"]>;
}

interface PreviewTombstone {
  documentId: string;
  status: PreviewStatus;
  expiresAt: number;
}

export type CadEditCapabilityErrorCode =
  | "EDIT_CANCELLED"
  | "EDIT_PREVIEW_UNKNOWN"
  | "EDIT_PREVIEW_REUSED"
  | "EDIT_PREVIEW_REJECTED"
  | "EDIT_PREVIEW_STALE"
  | "EDIT_PREVIEW_EXPIRED"
  | "EDIT_PREVIEW_EVICTED"
  | "EDIT_APPROVAL_REQUIRED"
  | "EDIT_DOCUMENT_MISMATCH";

export class CadEditCapabilityError extends Error {
  readonly code: CadEditCapabilityErrorCode;
  readonly currentRevision: number | null;

  constructor(code: CadEditCapabilityErrorCode, message: string, currentRevision: number | null = null) {
    super(message);
    this.name = "CadEditCapabilityError";
    this.code = code;
    this.currentRevision = currentRevision;
  }
}

export interface CadEditCapabilityComposition {
  module: CadCapabilityModule;
  transactions: CadCommittedTransactionStore;
}

export interface CadEditCapabilityDependencies {
  now?: () => number;
}

export function createEditCapabilityComposition(
  history: CadEditHistory,
  dependencies: CadEditCapabilityDependencies = {}
): CadEditCapabilityComposition {
  const now = dependencies.now ?? Date.now;
  const activePreviews = new Map<string, StoredPreview>();
  const previewsByDocument = new Map<string, string[]>();
  const tombstones = new Map<string, PreviewTombstone>();
  const tombstonesByDocument = new Map<string, string[]>();

  function retire(previewId: string, status: PreviewStatus): void {
    const stored = activePreviews.get(previewId);
    if (!stored) return;
    activePreviews.delete(previewId);
    const ids = previewsByDocument.get(stored.documentId);
    if (ids) {
      const index = ids.indexOf(previewId);
      if (index >= 0) ids.splice(index, 1);
      if (ids.length === 0) previewsByDocument.delete(stored.documentId);
    }
    appendTombstone(previewId, stored.documentId, status);
  }

  function appendTombstone(previewId: string, documentId: string, status: PreviewStatus): void {
    pruneTombstones(documentId);
    const ids = tombstonesByDocument.get(documentId) ?? [];
    tombstones.set(previewId, {
      documentId,
      status,
      expiresAt: now() + PREVIEW_TOMBSTONE_TTL_MS
    });
    ids.push(previewId);
    while (ids.length > MAX_PREVIEW_TOMBSTONES_PER_DOCUMENT) {
      tombstones.delete(ids.shift()!);
    }
    tombstonesByDocument.set(documentId, ids);
  }

  function pruneTombstones(documentId: string): void {
    const ids = tombstonesByDocument.get(documentId);
    if (!ids) return;
    while (ids.length > 0) {
      const tombstone = tombstones.get(ids[0]!);
      if (tombstone && tombstone.expiresAt > now()) break;
      tombstones.delete(ids.shift()!);
    }
    if (ids.length === 0) tombstonesByDocument.delete(documentId);
  }

  function forgetTombstone(previewId: string, documentId: string): void {
    tombstones.delete(previewId);
    const ids = tombstonesByDocument.get(documentId);
    if (!ids) return;
    const index = ids.indexOf(previewId);
    if (index >= 0) ids.splice(index, 1);
    if (ids.length === 0) tombstonesByDocument.delete(documentId);
  }

  function expireDocument(documentId: string): void {
    const cutoff = now() - PREVIEW_TTL_MS;
    for (const previewId of [...(previewsByDocument.get(documentId) ?? [])]) {
      const stored = activePreviews.get(previewId);
      if (stored && stored.createdAt <= cutoff) retire(previewId, "expired");
    }
  }

  function assertDocument(documentId: string, expectedDocumentId: string): void {
    if (documentId !== expectedDocumentId) {
      throw new CadEditCapabilityError(
        "EDIT_DOCUMENT_MISMATCH",
        "Edit preview document does not match the approved request."
      );
    }
  }

  function requireLifecycle(previewId: string, documentId: string): StoredPreview {
    const stored = activePreviews.get(previewId);
    if (stored) {
      expireDocument(stored.documentId);
      const active = activePreviews.get(previewId);
      if (!active) throw lifecycleError("expired", history.current().revision);
      assertDocument(active.documentId, documentId);
      return active;
    }

    const retained = tombstones.get(previewId);
    if (retained && retained.expiresAt <= now()) {
      forgetTombstone(previewId, retained.documentId);
    } else {
      pruneTombstones(documentId);
    }
    const tombstone = tombstones.get(previewId);
    if (!tombstone) {
      throw new CadEditCapabilityError("EDIT_PREVIEW_UNKNOWN", "Edit preview ID is not known.");
    }
    assertDocument(tombstone.documentId, documentId);
    throw lifecycleError(tombstone.status, history.current().revision);
  }

  const module: CadCapabilityModule = {
    names: ["edit.preview", "edit.apply", "edit.undo", "edit.redo"] as const satisfies readonly CadCapabilityName[],
    async execute(name, input, signal) {
      requireNotAborted(signal);
      switch (name) {
        case "edit.preview":
          return createPreview(input);
        case "edit.apply":
          return applyPreview(input);
        case "edit.undo":
          return applyHistory("undo", input);
        case "edit.redo":
          return applyHistory("redo", input);
        default:
          throw new Error(`Unsupported edit capability: ${name}`);
      }
    }
  };

  function createPreview(input: unknown): CadEditPreviewResponse {
    const request = parseCadEditPreviewRequest(input);
    expireDocument(request.batch.documentId);
    const preview = history.preview(request.batch);
    const previewId = randomUUID();
    const existing = previewsByDocument.get(request.batch.documentId) ?? [];
    while (existing.length >= MAX_PREVIEWS_PER_DOCUMENT) retire(existing[0]!, "evicted");
    activePreviews.set(previewId, {
      documentId: request.batch.documentId,
      createdAt: now(),
      preview
    });
    (previewsByDocument.get(request.batch.documentId) ?? existing).push(previewId);
    if (!previewsByDocument.has(request.batch.documentId)) {
      previewsByDocument.set(request.batch.documentId, existing);
    }
    return {
      previewId,
      documentId: request.batch.documentId,
      transactionId: preview.transactionId,
      baseRevision: preview.baseRevision,
      nextRevision: preview.nextRevision,
      changeCount: preview.changes.length,
      changesTruncated: preview.changes.length > MAX_CAD_EDIT_PREVIEW_CHANGES,
      changes: structuredClone(preview.changes.slice(0, MAX_CAD_EDIT_PREVIEW_CHANGES)),
      warningCount: preview.warnings.length,
      warningsTruncated: preview.warnings.length > MAX_CAD_EDIT_PREVIEW_WARNINGS,
      warnings: structuredClone(preview.warnings.slice(0, MAX_CAD_EDIT_PREVIEW_WARNINGS))
    };
  }

  function applyPreview(input: unknown): CadEditApplyResponse {
    const request = parseApproval(input);
    const stored = requireLifecycle(request.previewId, request.documentId);
    if (!request.approved) {
      retire(request.previewId, "rejected");
      throw new CadEditCapabilityError("EDIT_APPROVAL_REQUIRED", "Edit preview requires explicit approval.");
    }
    const current = history.current();
    if (
      request.expectedRevision !== stored.preview.baseRevision ||
      current.revision !== stored.preview.baseRevision ||
      current.documentId !== stored.documentId
    ) {
      retire(request.previewId, "stale");
      throw new CadEditCapabilityError(
        "EDIT_PREVIEW_STALE",
        "Edit preview no longer matches the current document revision.",
        current.revision
      );
    }
    try {
      const currentAfter = history.apply(stored.preview);
      retire(request.previewId, "applied");
      return {
        documentId: currentAfter.documentId,
        revision: currentAfter.revision,
        transactionId: stored.preview.transactionId,
        changeCount: stored.preview.changes.length
      };
    } catch (error) {
      if (error instanceof CadEditError && error.code === "EDIT_REVISION_CONFLICT") {
        retire(request.previewId, "stale");
        throw new CadEditCapabilityError(
          "EDIT_PREVIEW_STALE",
          "Edit preview no longer matches the current document revision.",
          history.current().revision
        );
      }
      throw error;
    }
  }

  function applyHistory(action: "undo" | "redo", input: unknown): CadEditApplyResponse {
    const request = parseApprovedHistoryRequest(input);
    const current = history.current();
    assertDocument(current.documentId, request.documentId);
    const transition = action === "undo"
      ? history.undoWithTransaction(request.expectedRevision)
      : history.redoWithTransaction(request.expectedRevision);
    return {
      documentId: transition.current.documentId,
      revision: transition.current.revision,
      transactionId: transition.transaction.batch.transactionId,
      changeCount: transition.transaction.changes.length
    };
  }

  return { module, transactions: history };
}

function requireNotAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw new CadEditCapabilityError(
      "EDIT_CANCELLED",
      "CAD edit operation was cancelled."
    );
  }
}

function parseApproval(input: unknown): {
  previewId: string;
  documentId: string;
  expectedRevision: number;
  approved: boolean;
} {
  const value = asRecord(input);
  if (value.approved === true) return parseCadEditApplyRequest(input);
  const { previewId, documentId, expectedRevision, approved } = value;
  if (
    approved !== false ||
    Object.keys(value).some((key) => !["previewId", "documentId", "expectedRevision", "approved"].includes(key)) ||
    typeof previewId !== "string" || !isUuid(previewId) || typeof documentId !== "string" ||
    !isRevision(expectedRevision)
  ) {
    throw new TypeError("Invalid edit apply request.");
  }
  return { previewId, documentId, expectedRevision, approved };
}

function parseApprovedHistoryRequest(input: unknown): CadEditHistoryRequest {
  const value = asRecord(input);
  if (value.approved !== true) {
    throw new CadEditCapabilityError("EDIT_APPROVAL_REQUIRED", "Edit history operation requires explicit approval.");
  }
  return parseCadEditHistoryRequest(input);
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("Expected edit capability input object.");
  }
  return value as Record<string, unknown>;
}

function isRevision(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function lifecycleError(status: PreviewStatus, currentRevision: number): CadEditCapabilityError {
  switch (status) {
    case "applied":
      return new CadEditCapabilityError("EDIT_PREVIEW_REUSED", "Edit preview has already been applied.");
    case "rejected":
      return new CadEditCapabilityError("EDIT_PREVIEW_REJECTED", "Edit preview was rejected.");
    case "stale":
      return new CadEditCapabilityError("EDIT_PREVIEW_STALE", "Edit preview is stale.", currentRevision);
    case "expired":
      return new CadEditCapabilityError("EDIT_PREVIEW_EXPIRED", "Edit preview has expired.");
    case "evicted":
      return new CadEditCapabilityError("EDIT_PREVIEW_EVICTED", "Edit preview was evicted by the document preview limit.");
  }
}
