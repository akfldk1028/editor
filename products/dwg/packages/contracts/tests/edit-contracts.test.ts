import assert from "node:assert/strict";
import test from "node:test";

import {
  cadEditApplyRequestSchema,
  cadEditErrorResponseSchema,
  cadEditHistoryRequestSchema,
  cadEditPreviewRequestSchema,
  cadEditPreviewResponseSchema,
  parseCadEditBatch
} from "../src/index.js";

const transactionId = "8df2be6a-1c60-4c8a-b7a1-0a5feef4b39c";
const commandId = "8a4479c9-aa40-45e4-9d57-231775fda1e3";
const skillRunId = "5e96c474-5183-45fc-8ccd-b97b64a52061";
const documentId = "drawing:fixture";

function userOrigin() {
  return { kind: "user" as const, id: "user:local" };
}

function guardedProposal(operation: Record<string, unknown>, overrides: Record<string, unknown> = {}) {
  return {
    commandId,
    expectedRevision: 7,
    origin: userOrigin(),
    preconditions: [{ target: "handle:1A", field: "exists", equals: true }],
    operation,
    ...overrides
  };
}

function batch(commands: unknown[]) {
  return {
    schemaVersion: "cad-edit/v1",
    transactionId,
    documentId,
    expectedRevision: 7,
    commands
  };
}

function previewResponse(baseRevision: number, nextRevision: number) {
  return {
    previewId: transactionId,
    documentId,
    transactionId,
    baseRevision,
    nextRevision,
    changeCount: 0,
    changesTruncated: false,
    changes: [],
    warningCount: 0,
    warningsTruncated: false,
    warnings: []
  };
}

function entityDeleteChange() {
  return {
    commandId,
    kind: "entity.delete" as const,
    targetId: "h:1A",
    before: { id: "h:1A", handle: "1A", type: "TEXT", layer: "0", bbox: null, text: "Old" },
    after: null
  };
}

test("accepts one guarded example of every deterministic edit command", () => {
  const parsed = parseCadEditBatch(batch([
    guardedProposal({ kind: "layer.create", layerId: "layer:created:annotations", name: "Annotations", color: 3 }),
    guardedProposal({ kind: "layer.update", layerId: "layer:imported:0", visible: false }),
    guardedProposal({ kind: "text.replace", handle: "1A", text: "Updated note" }),
    guardedProposal({ kind: "entity.move", handles: ["1A"], delta: [1, -2, 0] }),
    guardedProposal({ kind: "entity.copy", handles: ["1B"], delta: [0, 0, 5] }),
    guardedProposal({ kind: "entity.delete", handles: ["1C"] })
  ]));

  assert.equal(parsed.commands.length, 6);
  assert.equal(parsed.commands[0]?.operation.kind, "layer.create");
  assert.equal(parsed.commands[5]?.operation.kind, "entity.delete");
});

test("accepts a UUID-scoped skill origin", () => {
  const parsed = parseCadEditBatch(batch([
    guardedProposal(
      { kind: "entity.move", handles: ["1A"], delta: [0, 0, 0] },
      { origin: { kind: "skill", id: "skill:align", skillVersion: "1.2.0", runId: skillRunId } }
    )
  ]));

  assert.equal(parsed.commands[0]?.origin.kind, "skill");
});

test("rejects empty batches and unguarded commands before mutation", () => {
  assert.throws(() => parseCadEditBatch(batch([])));
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "entity.delete", handles: ["1A"] }, { preconditions: [] })
  ])));
});

test("rejects a proposal whose expected revision differs from its batch", () => {
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "entity.delete", handles: ["1A"] }, { expectedRevision: 8 })
  ])));
});

test("rejects empty or duplicate entity handles", () => {
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "entity.move", handles: [""], delta: [0, 0, 0] })
  ])));
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "entity.copy", handles: ["1A", "1A"], delta: [0, 0, 0] })
  ])));
});

test("bounds edit batches to one hundred commands and two hundred handles per command", () => {
  const commands = Array.from({ length: 101 }, (_, index) => guardedProposal(
    { kind: "entity.delete", handles: [`H${index}`] },
    { commandId: `20000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}` }
  ));
  assert.throws(() => parseCadEditBatch(batch(commands)));
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({
      kind: "entity.move",
      handles: Array.from({ length: 201 }, (_, index) => `H${index}`),
      delta: [0, 0, 0]
    })
  ])));
});

test("rejects non-finite deltas and colors outside the AutoCAD Color Index range", () => {
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "entity.move", handles: ["1A"], delta: [Infinity, 0, 0] })
  ])));
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "layer.create", layerId: "layer:created:notes", name: "Notes", color: 0 })
  ])));
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "layer.update", layerId: "layer:created:notes", color: 256 })
  ])));
});

test("rejects invalid layer IDs, unknown keys, and overlong replacement text", () => {
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "layer.create", layerId: "layer:custom:notes", name: "Notes", color: 7 })
  ])));
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "entity.delete", handles: ["1A"], unsafe: true })
  ])));
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "text.replace", handle: "1A", text: "x".repeat(16_385) })
  ])));
});

test("rejects layer updates without a mutable field", () => {
  assert.throws(() => parseCadEditBatch(batch([
    guardedProposal({ kind: "layer.update", layerId: "layer:imported:0" })
  ])));
});

test("strictly validates literal approval requests and typed preview evidence", () => {
  assert.equal(cadEditPreviewRequestSchema.safeParse({ batch: batch([
    guardedProposal({ kind: "entity.delete", handles: ["1A"] })
  ]) }).success, true);
  assert.equal(cadEditPreviewRequestSchema.safeParse({ batch: batch([
    guardedProposal({ kind: "entity.delete", handles: ["1A"] })
  ]), extra: true }).success, false);
  assert.equal(cadEditApplyRequestSchema.safeParse({ previewId: transactionId, documentId, expectedRevision: 7, approved: true }).success, true);
  assert.equal(cadEditApplyRequestSchema.safeParse({ previewId: transactionId, documentId, expectedRevision: 7, approved: false }).success, false);
  assert.equal(cadEditHistoryRequestSchema.safeParse({ documentId, expectedRevision: 7, approved: true }).success, true);
  assert.equal(cadEditHistoryRequestSchema.safeParse({ documentId, expectedRevision: 7, approved: true, extra: true }).success, false);
  assert.equal(cadEditPreviewResponseSchema.safeParse({
    previewId: transactionId,
    documentId,
    transactionId,
    baseRevision: 7,
    nextRevision: 8,
    changeCount: 1,
    changesTruncated: false,
    changes: [entityDeleteChange()],
    warningCount: 0,
    warningsTruncated: false,
    warnings: []
  }).success, true);
  assert.equal(cadEditPreviewResponseSchema.safeParse({
    previewId: transactionId,
    documentId,
    transactionId,
    baseRevision: 7,
    nextRevision: 8,
    changeCount: 0,
    changesTruncated: false,
    changes: [],
    warningCount: 0,
    warningsTruncated: false,
    warnings: [],
    engine: {}
  }).success, false);
});

test("stale edit failures require an authoritative current revision", () => {
  assert.equal(cadEditErrorResponseSchema.safeParse({
    error: {
      code: "EDIT_PREVIEW_STALE",
      message: "CAD edit operation could not be completed.",
      currentRevision: 9
    }
  }).success, true);
  assert.equal(cadEditErrorResponseSchema.safeParse({
    error: {
      code: "EDIT_PREVIEW_STALE",
      message: "CAD edit operation could not be completed."
    }
  }).success, false);
  assert.equal(cadEditErrorResponseSchema.safeParse({
    error: {
      code: "EDIT_PREVIEW_REUSED",
      message: "CAD edit operation could not be completed.",
      currentRevision: 9
    }
  }).success, false);
});

test("preview responses bound evidence and strictly describe every omission", () => {
  assert.equal(cadEditPreviewResponseSchema.safeParse({
    ...previewResponse(7, 8),
    changeCount: 201,
    changesTruncated: true,
    changes: Array.from({ length: 200 }, entityDeleteChange),
    warningCount: 101,
    warningsTruncated: true,
    warnings: Array.from({ length: 100 }, (_, index) => `warning-${index}`)
  }).success, true);

  assert.equal(cadEditPreviewResponseSchema.safeParse({
    ...previewResponse(7, 8),
    changeCount: 201,
    changesTruncated: true,
    changes: Array.from({ length: 201 }, entityDeleteChange)
  }).success, false);
  assert.equal(cadEditPreviewResponseSchema.safeParse({
    ...previewResponse(7, 8),
    warningCount: 101,
    warningsTruncated: true,
    warnings: Array.from({ length: 101 }, (_, index) => `warning-${index}`)
  }).success, false);
  assert.equal(cadEditPreviewResponseSchema.safeParse({
    ...previewResponse(7, 8),
    changeCount: 1,
    changesTruncated: false
  }).success, false);
});

test("rejects preview revisions that do not advance exactly once", () => {
  assert.equal(cadEditPreviewResponseSchema.safeParse(previewResponse(7, 7)).success, false);
  assert.equal(cadEditPreviewResponseSchema.safeParse(previewResponse(7, 6)).success, false);
});

test("rejects preview revisions outside the safe integer range", () => {
  assert.equal(cadEditPreviewResponseSchema.safeParse(
    previewResponse(Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER + 1)
  ).success, false);
  assert.equal(cadEditPreviewResponseSchema.safeParse(
    previewResponse(Number.MAX_SAFE_INTEGER + 1, Number.MAX_SAFE_INTEGER + 2)
  ).success, false);
});
