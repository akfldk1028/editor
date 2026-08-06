import assert from "node:assert/strict";
import test from "node:test";

import type {
  CadEditBatch,
  CadEditCommand,
  CadCommandProposal,
  CadEditPrecondition
} from "@dwg/contracts";
import type { CadDocumentSnapshot } from "@dwg/cad-document";
import { CadEditError, previewEditBatch } from "../src/index.js";

const transactionId = "8df2be6a-1c60-4c8a-b7a1-0a5feef4b39c";
const commandIds = [
  "8a4479c9-aa40-45e4-9d57-231775fda1e3",
  "897b729b-b1bd-4c9e-b417-2a159eabb7db",
  "bb8df9b4-ecbd-4ae6-a747-3ef15d09693c",
  "d55f1f2a-37d6-4d7a-9ca3-9c9f88689ad2",
  "cda54d38-2feb-479f-a43f-ae7b305189e8",
  "ef93af44-9d3e-46dd-aa12-93381ce66eaa"
] as const;

function snapshot(): CadDocumentSnapshot {
  return {
    documentId: "drawing:fixture",
    revision: 7,
    sourceSha256: "A".repeat(64),
    drawingVersion: "AC1032",
    units: "Millimeters",
    index: {
      schemaVersion: "cad-index/v0.2",
      drawingId: "drawing:fixture",
      source: { kind: "dxf", displayName: "fixture.dxf", parser: "fixture" },
      summary: {
        entityCount: 6,
        layerCount: 2,
        unsupportedCount: 0,
        modelSpaceCount: 6,
        paperSpaceCount: 0
      },
      drawing: { fileVersion: "AC1032", units: "Millimeters" },
      layers: [
        { name: "0", entityCount: 5, visible: true, frozen: false, color: 7, locked: false },
        { name: "Notes", entityCount: 1, visible: true, frozen: false, color: 2, locked: null }
      ],
      unsupported: [],
      entities: [
        entity("10", "LINE", "0", null, { kind: "line", start: [1, 2, 3], end: [4, 5, 6] }),
        entity("11", "CIRCLE", "0", null, { kind: "circle", center: [10, 20, 30], radius: 5, normal: [0, 0, 1] }),
        entity("12", "ARC", "0", null, { kind: "arc", center: [2, 4, 6], radius: 3, startAngle: 0, endAngle: 90, normal: [0, 0, 1] }),
        entity("13", "LWPOLYLINE", "0", null, {
          kind: "lwpolyline",
          vertices: [
            { point: [1, 1, 4], bulge: 0, startWidth: 0, endWidth: 0 },
            { point: [3, 1, 4], bulge: 0, startWidth: 0, endWidth: 0 }
          ],
          closed: false,
          elevation: 4,
          normal: [0, 0, 1]
        }),
        entity("14", "TEXT", "0", "old text", { kind: "text", insertionPoint: [8, 9, 0], alignmentPoint: null, height: 2, rotation: 0, width: null }),
        entity("15", "MTEXT", "Notes", "old mtext", { kind: "text", insertionPoint: [11, 12, 0], alignmentPoint: [13, 14, 0], height: 2, rotation: 0, width: null })
      ]
    },
    layers: [
      { id: "layer:imported:MA", name: "0", color: 7, visible: true, frozen: false, locked: false },
      { id: "layer:imported:Tm90ZXM", name: "Notes", color: 2, visible: true, frozen: false, locked: null }
    ]
  };
}

function entity(
  handle: string,
  type: string,
  layer: string,
  text: string | null,
  geometry: CadDocumentSnapshot["index"]["entities"][number]["geometry"]
) {
  const point = geometry.kind === "line"
    ? geometry.start
    : geometry.kind === "circle" || geometry.kind === "arc"
      ? geometry.center
      : geometry.kind === "lwpolyline"
        ? geometry.vertices[0]?.point ?? [0, 0, 0]
        : geometry.kind === "text"
          ? geometry.insertionPoint
          : [0, 0, 0] as [number, number, number];
  return {
    id: `h:${handle}`,
    handle,
    type,
    layer,
    space: "model" as const,
    layout: "Model",
    bbox: { min: [...point] as [number, number, number], max: [...point] as [number, number, number] },
    text,
    blockName: null,
    attributes: {},
    warnings: [],
    geometry
  };
}

function proposal(
  operation: CadEditCommand,
  commandIndex = 0,
  preconditions: CadEditPrecondition[] = operationTargets(operation).map((target) => ({
    target,
    field: "exists",
    equals: true
  }))
): CadCommandProposal {
  return {
    commandId: commandIds[commandIndex]!,
    expectedRevision: 7,
    origin: { kind: "user", id: "user:local" },
    preconditions,
    operation
  };
}

function operationTargets(operation: CadEditCommand): string[] {
  if (operation.kind === "layer.create" || operation.kind === "layer.update") return [operation.layerId];
  if (operation.kind === "text.replace") return [operation.handle];
  return operation.handles;
}

function batch(commands: CadCommandProposal[], overrides: Partial<CadEditBatch> = {}): CadEditBatch {
  return {
    schemaVersion: "cad-edit/v1",
    transactionId,
    documentId: "drawing:fixture",
    expectedRevision: 7,
    commands,
    ...overrides
  };
}

function entityByHandle(result: CadDocumentSnapshot, handle: string) {
  return result.index.entities.find((candidate) => candidate.handle === handle);
}

test("previews layer creation and updates with public typed layer diffs", () => {
  const initial = snapshot();
  const preview = previewEditBatch(initial, batch([
    proposal(
      { kind: "layer.create", layerId: "layer:created:annotations", name: "Annotations", color: 3 },
      0,
      [{ target: "layer:created:annotations", field: "exists", equals: false }]
    ),
    proposal(
      { kind: "layer.update", layerId: "layer:imported:MA", name: "Base", color: 1, visible: false, locked: true },
      1
    )
  ]));

  assert.equal(preview.baseRevision, 7);
  assert.equal(preview.nextRevision, 8);
  assert.equal(preview.snapshot.revision, 8);
  assert.deepEqual(preview.snapshot.layers, [
    { id: "layer:imported:MA", name: "Base", color: 1, visible: false, frozen: false, locked: true },
    { id: "layer:imported:Tm90ZXM", name: "Notes", color: 2, visible: true, frozen: false, locked: null },
    { id: "layer:created:annotations", name: "Annotations", color: 3, visible: true, frozen: false, locked: null }
  ]);
  assert.deepEqual(preview.changes, [
    {
      commandId: commandIds[0], kind: "layer.create", targetId: "layer:created:annotations", before: null,
      after: { id: "layer:created:annotations", name: "Annotations", color: 3, visible: true, frozen: false, locked: null }
    },
    {
      commandId: commandIds[1], kind: "layer.update", targetId: "layer:imported:MA",
      before: { id: "layer:imported:MA", name: "0", color: 7, visible: true, frozen: false, locked: false },
      after: { id: "layer:imported:MA", name: "Base", color: 1, visible: false, frozen: false, locked: true }
    }
  ]);
  assert.deepEqual(initial, snapshot());
});

test("replaces TEXT and MTEXT values with precise typed evidence", () => {
  const preview = previewEditBatch(snapshot(), batch([
    proposal({ kind: "text.replace", handle: "14", text: "new text" }),
    proposal({ kind: "text.replace", handle: "15", text: "new mtext" }, 1)
  ]));

  assert.equal(entityByHandle(preview.snapshot, "14")?.text, "new text");
  assert.equal(entityByHandle(preview.snapshot, "15")?.text, "new mtext");
  assert.deepEqual(preview.changes.map((change) => [
    change.kind,
    change.before !== null && "text" in change.before ? change.before.text : null,
    change.after !== null && "text" in change.after ? change.after.text : null
  ]), [
    ["text.replace", "old text", "new text"],
    ["text.replace", "old mtext", "new mtext"]
  ]);
});

test("moves each supported geometry and its bounding box by the exact delta", () => {
  const preview = previewEditBatch(snapshot(), batch([
    proposal({ kind: "entity.move", handles: ["10", "11", "12", "13"], delta: [10, -2, 5] })
  ]));

  assert.deepEqual(entityByHandle(preview.snapshot, "10")?.geometry, { kind: "line", start: [11, 0, 8], end: [14, 3, 11] });
  assert.deepEqual(entityByHandle(preview.snapshot, "11")?.geometry, { kind: "circle", center: [20, 18, 35], radius: 5, normal: [0, 0, 1] });
  assert.deepEqual(entityByHandle(preview.snapshot, "12")?.geometry, { kind: "arc", center: [12, 2, 11], radius: 3, startAngle: 0, endAngle: 90, normal: [0, 0, 1] });
  assert.deepEqual(entityByHandle(preview.snapshot, "13")?.geometry, {
    kind: "lwpolyline",
    vertices: [
      { point: [11, -1, 9], bulge: 0, startWidth: 0, endWidth: 0 },
      { point: [13, -1, 9], bulge: 0, startWidth: 0, endWidth: 0 }
    ],
    closed: false,
    elevation: 9,
    normal: [0, 0, 1]
  });
  assert.deepEqual(entityByHandle(preview.snapshot, "10")?.bbox, { min: [11, 0, 8], max: [11, 0, 8] });
});

test("emits one complete resolved command for each moved target", () => {
  const preview = previewEditBatch(snapshot(), batch([
    proposal({ kind: "entity.move", handles: ["10", "11"], delta: [1, 2, 3] })
  ]));

  assert.deepEqual(preview.resolvedCommands.map((resolved) => ({
    commandId: resolved.proposal.commandId,
    beforeId: resolved.before?.id,
    resultId: resolved.result?.id
  })), [
    { commandId: commandIds[0], beforeId: "h:10", resultId: "h:10" },
    { commandId: commandIds[0], beforeId: "h:11", resultId: "h:11" }
  ]);
});

test("surfaces only target warnings with deterministic per-target and preview de-duplication", () => {
  const initial = snapshot();
  entityByHandle(initial, "10")!.warnings = ["z-warning", "shared-warning", "z-warning"];
  entityByHandle(initial, "11")!.warnings = ["a-warning", "shared-warning"];
  entityByHandle(initial, "15")!.warnings = ["unrelated-warning"];
  const preview = previewEditBatch(initial, batch([
    proposal({ kind: "entity.move", handles: ["10", "11"], delta: [1, 0, 0] })
  ]));

  assert.deepEqual(preview.resolvedCommands.map((resolved) => resolved.warnings), [
    ["shared-warning", "z-warning"],
    ["a-warning", "shared-warning"]
  ]);
  assert.deepEqual(preview.warnings, ["a-warning", "shared-warning", "z-warning"]);
});

test("copies only supported entities with a null handle and deterministic temporary ID", () => {
  const preview = previewEditBatch(snapshot(), batch([
    proposal({ kind: "entity.copy", handles: ["10"], delta: [2, 3, 4] }, 2)
  ]));
  const copy = preview.snapshot.index.entities.at(-1);

  assert.deepEqual(copy, {
    ...entity("10", "LINE", "0", null, { kind: "line", start: [3, 5, 7], end: [6, 8, 10] }),
    id: `copy:${transactionId}:${commandIds[2]}:0`,
    handle: null,
    bbox: { min: [3, 5, 7], max: [3, 5, 7] }
  });
  assert.deepEqual(preview.changes[0], {
    commandId: commandIds[2], kind: "entity.copy", targetId: `copy:${transactionId}:${commandIds[2]}:0`, before: null,
    after: { id: `copy:${transactionId}:${commandIds[2]}:0`, handle: null, type: "LINE", layer: "0", bbox: { min: [3, 5, 7], max: [3, 5, 7] }, text: null }
  });
});

test("emits one complete resolved command for each copied target", () => {
  const preview = previewEditBatch(snapshot(), batch([
    proposal({ kind: "entity.copy", handles: ["10", "11"], delta: [1, 0, 0] }, 2)
  ]));

  assert.deepEqual(preview.resolvedCommands.map((resolved) => ({
    beforeId: resolved.before?.id,
    resultId: resolved.result?.id,
    resultHandle: resolved.result !== null && "handle" in resolved.result
      ? resolved.result.handle
      : "not-an-entity"
  })), [
    {
      beforeId: "h:10",
      resultId: `copy:${transactionId}:${commandIds[2]}:0`,
      resultHandle: null
    },
    {
      beforeId: "h:11",
      resultId: `copy:${transactionId}:${commandIds[2]}:1`,
      resultHandle: null
    }
  ]);
});

test("rejects a deterministic copy ID that collides with an existing entity ID", () => {
  const initial = snapshot();
  const copyId = `copy:${transactionId}:${commandIds[2]}:0`;
  initial.index.entities[5]!.id = copyId;
  const before = structuredClone(initial);

  assert.throws(
    () => previewEditBatch(initial, batch([
      proposal({ kind: "entity.copy", handles: ["10"], delta: [2, 3, 4] }, 2)
    ])),
    (error) => error instanceof CadEditError && error.code === "EDIT_COPY_ID_COLLISION"
  );
  assert.deepEqual(initial, before);
});

test("rejects a copy ID that collides with an earlier planned copy in the same preview", () => {
  const initial = snapshot();
  const before = structuredClone(initial);
  const first = proposal({ kind: "entity.copy", handles: ["10"], delta: [1, 0, 0] }, 2);
  const second = {
    ...proposal({ kind: "entity.copy", handles: ["11"], delta: [0, 1, 0] }, 3),
    commandId: first.commandId
  };

  assert.throws(
    () => previewEditBatch(initial, batch([first, second])),
    (error) => error instanceof CadEditError && error.code === "EDIT_COPY_ID_COLLISION"
  );
  assert.deepEqual(initial, before);
});

test("deletes each supported geometry with a null after-state", () => {
  const preview = previewEditBatch(snapshot(), batch([
    proposal({ kind: "entity.delete", handles: ["10", "11", "12", "13"] })
  ]));

  assert.equal(preview.snapshot.index.entities.length, 2);
  assert.deepEqual(preview.changes.map((change) => [change.targetId, change.after]), [
    ["h:10", null], ["h:11", null], ["h:12", null], ["h:13", null]
  ]);
});

test("emits one complete resolved command for each deleted target", () => {
  const preview = previewEditBatch(snapshot(), batch([
    proposal({ kind: "entity.delete", handles: ["10", "11"] })
  ]));

  assert.deepEqual(preview.resolvedCommands.map((resolved) => ({
    beforeId: resolved.before?.id,
    result: resolved.result
  })), [
    { beforeId: "h:10", result: null },
    { beforeId: "h:11", result: null }
  ]);
});

test("surfaces source warning evidence for text, copy, and delete commands", () => {
  const textSnapshot = snapshot();
  entityByHandle(textSnapshot, "14")!.warnings = ["text-warning", "text-warning"];
  const textPreview = previewEditBatch(textSnapshot, batch([
    proposal({ kind: "text.replace", handle: "14", text: "new text" })
  ]));

  const copySnapshot = snapshot();
  entityByHandle(copySnapshot, "10")!.warnings = ["copy-warning"];
  const copyPreview = previewEditBatch(copySnapshot, batch([
    proposal({ kind: "entity.copy", handles: ["10"], delta: [1, 0, 0] }, 2)
  ]));

  const deleteSnapshot = snapshot();
  entityByHandle(deleteSnapshot, "11")!.warnings = ["delete-warning"];
  const deletePreview = previewEditBatch(deleteSnapshot, batch([
    proposal({ kind: "entity.delete", handles: ["11"] })
  ]));

  assert.deepEqual(
    [textPreview, copyPreview, deletePreview].map((preview) => ({
      resolved: preview.resolvedCommands[0]?.warnings,
      preview: preview.warnings
    })),
    [
      { resolved: ["text-warning"], preview: ["text-warning"] },
      { resolved: ["copy-warning"], preview: ["copy-warning"] },
      { resolved: ["delete-warning"], preview: ["delete-warning"] }
    ]
  );
});

test("rejects duplicate batch targets before mutation", () => {
  const initial = snapshot();
  const before = structuredClone(initial);
  assert.throws(() => previewEditBatch(initial, batch([
    proposal({ kind: "entity.move", handles: ["10"], delta: [1, 0, 0] }),
    proposal({ kind: "entity.delete", handles: ["10"] }, 1)
  ])), /duplicate/i);
  assert.deepEqual(initial, before);
});

test("rejects unsupported types instead of inventing geometry", () => {
  const initial = snapshot();
  initial.index.entities[0] = entity("10", "SPLINE", "0", null, { kind: "bbox", reason: "unsupported" });
  const before = structuredClone(initial);

  assert.throws(() => previewEditBatch(initial, batch([
    proposal({ kind: "entity.move", handles: ["10"], delta: [1, 0, 0] })
  ])), /unsupported/i);
  assert.deepEqual(initial, before);
});

test("rejects document, revision, and precondition conflicts before mutation", () => {
  const initial = snapshot();
  const before = structuredClone(initial);
  assert.throws(() => previewEditBatch(initial, batch([
    proposal({ kind: "entity.delete", handles: ["10"] })
  ], { documentId: "drawing:other" })), /document/i);
  assert.throws(() => previewEditBatch(initial, batch([
    { ...proposal({ kind: "entity.delete", handles: ["10"] }), expectedRevision: 6 }
  ], { expectedRevision: 6 })), /revision/i);
  assert.throws(() => previewEditBatch(initial, batch([
    proposal({ kind: "entity.delete", handles: ["10"] }, 0, [{ target: "10", field: "type", equals: "CIRCLE" }])
  ])), /precondition/i);
  assert.deepEqual(initial, before);
});

test("rejects a precondition that guards an unrelated entity", () => {
  const initial = snapshot();
  const before = structuredClone(initial);

  assert.throws(
    () => previewEditBatch(initial, batch([
      proposal(
        { kind: "entity.delete", handles: ["10"] },
        0,
        [{ target: "11", field: "type", equals: "CIRCLE" }]
      )
    ])),
    (error) => error instanceof CadEditError && error.code === "EDIT_PRECONDITION_SCOPE"
  );
  assert.deepEqual(initial, before);
});

test("rejects a multi-target command without precondition coverage for every target", () => {
  const initial = snapshot();
  const before = structuredClone(initial);

  assert.throws(
    () => previewEditBatch(initial, batch([
      proposal(
        { kind: "entity.move", handles: ["10", "11"], delta: [1, 0, 0] },
        0,
        [{ target: "10", field: "exists", equals: true }]
      )
    ])),
    (error) => error instanceof CadEditError && error.code === "EDIT_PRECONDITION_COVERAGE"
  );
  assert.deepEqual(initial, before);
});

test("requires layer creation to be guarded by exists false on its layer ID", () => {
  const initial = snapshot();
  const before = structuredClone(initial);

  assert.throws(
    () => previewEditBatch(initial, batch([
      proposal(
        { kind: "layer.create", layerId: "layer:created:new", name: "New", color: 7 },
        0,
        [{ target: "layer:created:new", field: "exists", equals: true }]
      )
    ])),
    (error) => error instanceof CadEditError && error.code === "EDIT_PRECONDITION_COVERAGE"
  );
  assert.deepEqual(initial, before);
});

test("rolls back the entire preview when command two of three fails", () => {
  const initial = snapshot();
  const before = structuredClone(initial);
  assert.throws(() => previewEditBatch(initial, batch([
    proposal({ kind: "entity.move", handles: ["10"], delta: [1, 0, 0] }),
    proposal({ kind: "text.replace", handle: "11", text: "not text" }, 1),
    proposal({ kind: "entity.delete", handles: ["12"] }, 2)
  ])), /TEXT|MTEXT|unsupported/i);
  assert.deepEqual(initial, before);
});
