import assert from "node:assert/strict";
import test from "node:test";

import type { CadEditBatch } from "@dwg/contracts";
import type { CadDocumentSnapshot } from "@dwg/cad-document";
import { createCadEditHistory } from "@dwg/cad-edit";

import { createEditCapabilityComposition } from "@dwg/cad-capabilities";

function snapshot(): CadDocumentSnapshot {
  return {
    documentId: "drawing:capabilities",
    revision: 0,
    sourceSha256: "A".repeat(64),
    drawingVersion: "AC1032",
    units: "Millimeters",
    index: {
      schemaVersion: "cad-index/v0.2",
      drawingId: "drawing:capabilities",
      source: { kind: "dxf", displayName: "capabilities.dxf", parser: "fixture" },
      summary: { entityCount: 1, layerCount: 1, unsupportedCount: 0, modelSpaceCount: 1, paperSpaceCount: 0 },
      drawing: { fileVersion: "AC1032", units: "Millimeters" },
      layers: [{ name: "0", entityCount: 1, visible: true, frozen: false, color: 7, locked: false }],
      unsupported: [],
      entities: [{
        id: "h:10", handle: "10", type: "TEXT", layer: "0", space: "model", layout: "Model",
        bbox: { min: [0, 0, 0], max: [0, 0, 0] }, text: "original", blockName: null,
        attributes: {}, warnings: [],
        geometry: { kind: "text", insertionPoint: [0, 0, 0], alignmentPoint: null, height: 1, rotation: 0, width: null }
      }]
    },
    layers: [{ id: "layer:imported:MA", name: "0", color: 7, visible: true, frozen: false, locked: false }]
  };
}

function uuid(index: number): string {
  return `10000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}`;
}

function batch(revision: number, index: number, text = `text-${index}`): CadEditBatch {
  return {
    schemaVersion: "cad-edit/v1",
    transactionId: uuid(index),
    documentId: "drawing:capabilities",
    expectedRevision: revision,
    commands: [{
      commandId: uuid(1000 + index),
      expectedRevision: revision,
      origin: { kind: "user", id: "user:local" },
      preconditions: [{ target: "10", field: "exists", equals: true }],
      operation: { kind: "text.replace", handle: "10", text }
    }]
  };
}

function largeSnapshot(entityCount: number): CadDocumentSnapshot {
  const value = snapshot();
  value.index.summary.entityCount = entityCount;
  value.index.summary.modelSpaceCount = entityCount;
  value.index.layers[0]!.entityCount = entityCount;
  value.index.entities = Array.from({ length: entityCount }, (_, index) => ({
    id: `h:H${index}`,
    handle: `H${index}`,
    type: "LINE",
    layer: "0",
    space: "model" as const,
    layout: "Model",
    bbox: { min: [index, 0, 0] as [number, number, number], max: [index + 1, 0, 0] as [number, number, number] },
    text: null,
    blockName: null,
    attributes: {},
    warnings: [`warning-${index.toString().padStart(3, "0")}`],
    geometry: { kind: "line" as const, start: [index, 0, 0] as [number, number, number], end: [index + 1, 0, 0] as [number, number, number] }
  }));
  return value;
}

function largeBatch(): CadEditBatch {
  const firstHandles = Array.from({ length: 200 }, (_, index) => `H${index}`);
  return {
    schemaVersion: "cad-edit/v1",
    transactionId: uuid(8_000),
    documentId: "drawing:capabilities",
    expectedRevision: 0,
    commands: [{
      commandId: uuid(8_001),
      expectedRevision: 0,
      origin: { kind: "user", id: "user:local" },
      preconditions: firstHandles.map((target) => ({ target, field: "exists" as const, equals: true })),
      operation: { kind: "entity.move", handles: firstHandles, delta: [1, 0, 0] }
    }, {
      commandId: uuid(8_002),
      expectedRevision: 0,
      origin: { kind: "user", id: "user:local" },
      preconditions: [{ target: "H200", field: "exists", equals: true }],
      operation: { kind: "entity.move", handles: ["H200"], delta: [1, 0, 0] }
    }]
  };
}

function codeOf(error: unknown): string | undefined {
  return typeof error === "object" && error !== null && "code" in error
    ? String(error.code)
    : undefined;
}

async function preview(
  composition: ReturnType<typeof createEditCapabilityComposition>,
  revision: number,
  index: number
) {
  return composition.module.execute("edit.preview", { batch: batch(revision, index) }) as Promise<{
    previewId: string;
    documentId: string;
    transactionId: string;
    baseRevision: number;
    nextRevision: number;
    changeCount: number;
    changesTruncated: boolean;
    changes: unknown[];
    warningCount: number;
    warningsTruncated: boolean;
    warnings: string[];
  }>;
}

test("edit preview exposes a bounded review summary without a document snapshot", async () => {
  const composition = createEditCapabilityComposition(createCadEditHistory(snapshot()));
  const result = await preview(composition, 0, 1);

  assert.match(result.previewId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  assert.deepEqual(
    Object.keys(result).sort(),
    [
      "baseRevision", "changeCount", "changes", "changesTruncated", "documentId", "nextRevision",
      "previewId", "transactionId", "warningCount", "warnings", "warningsTruncated"
    ]
  );
  assert.equal(result.baseRevision, 0);
  assert.equal(result.nextRevision, 1);
  assert.equal(result.changeCount, 1);
  assert.equal(result.changesTruncated, false);
  assert.equal(result.changes.length, 1);
  assert.equal(result.warningCount, 0);
  assert.equal(result.warningsTruncated, false);
  assert.deepEqual(result.warnings, []);
});

test("edit preview caps returned changes and warnings while reporting exact totals", async () => {
  const composition = createEditCapabilityComposition(createCadEditHistory(largeSnapshot(201)));
  const result = await composition.module.execute("edit.preview", { batch: largeBatch() }) as Awaited<ReturnType<typeof preview>>;

  assert.deepEqual(
    [result.changeCount, result.changes.length, result.changesTruncated],
    [201, 200, true]
  );
  assert.deepEqual(
    [result.warningCount, result.warnings.length, result.warningsTruncated],
    [201, 100, true]
  );
  assert.equal("snapshot" in result, false);
  assert.equal("resolvedCommands" in result, false);
});

test("edit apply consumes an approved preview once and shares its history transaction store", async () => {
  const history = createCadEditHistory(snapshot());
  const composition = createEditCapabilityComposition(history);
  assert.equal(composition.transactions, history);
  const proposed = await preview(composition, 0, 2);

  const applied = await composition.module.execute("edit.apply", {
    previewId: proposed.previewId,
    documentId: "drawing:capabilities",
    expectedRevision: 0,
    approved: true
  }) as { documentId: string; revision: number; transactionId: string; changeCount: number };

  assert.deepEqual(applied, {
    documentId: "drawing:capabilities", revision: 1, transactionId: uuid(2), changeCount: 1
  });
  assert.equal(composition.transactions.getCommittedTransaction(uuid(2))?.status, "applied");
  assert.equal(history.current().revision, 1);
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: proposed.previewId, documentId: "drawing:capabilities", expectedRevision: 1, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_REUSED"
  );
});

test("edit approval requests remain strict and do not commit arbitrary input", async () => {
  const history = createCadEditHistory(snapshot());
  const composition = createEditCapabilityComposition(history);
  const proposed = await preview(composition, 0, 50);

  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: proposed.previewId,
      documentId: "drawing:capabilities",
      expectedRevision: 0,
      approved: true,
      ignored: "untrusted"
    })
  );
  assert.equal(history.current().revision, 0);

  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: proposed.previewId,
      documentId: "drawing:capabilities",
      expectedRevision: 0,
      approved: false,
      ignored: "cannot reject another caller's preview"
    })
  );
  assert.equal(history.current().revision, 0);
  assert.equal((await composition.module.execute("edit.apply", {
    previewId: proposed.previewId,
    documentId: "drawing:capabilities",
    expectedRevision: 0,
    approved: true
  }) as { revision: number }).revision, 1);
});

test("edit apply denies unknown, cross-document, rejected, and stale previews with distinct lifecycle errors", async () => {
  const composition = createEditCapabilityComposition(createCadEditHistory(snapshot()));
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: uuid(99), documentId: "drawing:capabilities", expectedRevision: 0, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_UNKNOWN"
  );

  const crossDocument = await preview(composition, 0, 3);
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: crossDocument.previewId, documentId: "drawing:other", expectedRevision: 0, approved: true
    }),
    (error) => codeOf(error) === "EDIT_DOCUMENT_MISMATCH"
  );
  assert.equal((await composition.module.execute("edit.apply", {
    previewId: crossDocument.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
  }) as { revision: number }).revision, 1);

  const rejected = await preview(composition, 1, 4);
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: rejected.previewId, documentId: "drawing:capabilities", expectedRevision: 1, approved: false
    }),
    (error) => codeOf(error) === "EDIT_APPROVAL_REQUIRED"
  );
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: rejected.previewId, documentId: "drawing:capabilities", expectedRevision: 1, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_REJECTED"
  );

  const stale = await preview(composition, 1, 5);
  const fresh = await preview(composition, 1, 6);
  await composition.module.execute("edit.apply", {
    previewId: fresh.previewId, documentId: "drawing:capabilities", expectedRevision: 1, approved: true
  });
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: stale.previewId, documentId: "drawing:capabilities", expectedRevision: 1, approved: true
    }),
    (error) =>
      codeOf(error) === "EDIT_PREVIEW_STALE" &&
      (error as { currentRevision?: unknown }).currentRevision === 2
  );
});

test("edit undo and redo operate on the paired history and require the current document revision", async () => {
  const history = createCadEditHistory(snapshot());
  const composition = createEditCapabilityComposition(history);
  const proposed = await preview(composition, 0, 7);
  await composition.module.execute("edit.apply", {
    previewId: proposed.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
  });

  const undone = await composition.module.execute("edit.undo", {
    documentId: "drawing:capabilities", expectedRevision: 1, approved: true
  }) as { revision: number };
  const redone = await composition.module.execute("edit.redo", {
    documentId: "drawing:capabilities", expectedRevision: 2, approved: true
  }) as { revision: number };

  assert.deepEqual([undone.revision, redone.revision, composition.transactions.getCommittedTransaction(uuid(7))?.status], [2, 3, "applied"]);
  assert.equal(composition.transactions.getSaveState("drawing:capabilities", 3)?.current.revision, 3);
  await assert.rejects(
    () => composition.module.execute("edit.undo", {
      documentId: "drawing:capabilities", expectedRevision: 2, approved: true
    }),
    (error) => codeOf(error) === "EDIT_REVISION_CONFLICT"
  );
});

test("pre-aborted edit operations do not allocate consume or mutate lifecycle state", async () => {
  const history = createCadEditHistory(snapshot());
  const composition = createEditCapabilityComposition(history);
  const controller = new AbortController();
  controller.abort();

  await assert.rejects(
    () => composition.module.execute(
      "edit.preview",
      { batch: batch(0, 600) },
      controller.signal
    ),
    (error) => codeOf(error) === "EDIT_CANCELLED" &&
      error instanceof Error &&
      error.message === "CAD edit operation was cancelled."
  );

  const retained = [] as Awaited<ReturnType<typeof preview>>[];
  for (let index = 0; index < 20; index += 1) {
    retained.push(await preview(composition, 0, 601 + index));
  }
  const proposed = retained[0]!;

  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: proposed.previewId,
      documentId: "drawing:capabilities",
      expectedRevision: 0,
      approved: true
    }, controller.signal),
    (error) => codeOf(error) === "EDIT_CANCELLED"
  );
  assert.equal(history.current().revision, 0);
  assert.equal(composition.transactions.getCommittedTransaction(proposed.transactionId), null);

  assert.equal((await composition.module.execute("edit.apply", {
    previewId: proposed.previewId,
    documentId: "drawing:capabilities",
    expectedRevision: 0,
    approved: true
  }) as { revision: number }).revision, 1);

  await assert.rejects(
    () => composition.module.execute("edit.undo", {
      documentId: "drawing:capabilities",
      expectedRevision: 1,
      approved: true
    }, controller.signal),
    (error) => codeOf(error) === "EDIT_CANCELLED"
  );
  assert.deepEqual(
    [history.current().revision, composition.transactions.getCommittedTransaction(proposed.transactionId)?.status],
    [1, "applied"]
  );

  assert.equal((await composition.module.execute("edit.undo", {
    documentId: "drawing:capabilities",
    expectedRevision: 1,
    approved: true
  }) as { revision: number }).revision, 2);

  await assert.rejects(
    () => composition.module.execute("edit.redo", {
      documentId: "drawing:capabilities",
      expectedRevision: 2,
      approved: true
    }, controller.signal),
    (error) => codeOf(error) === "EDIT_CANCELLED"
  );
  assert.deepEqual(
    [history.current().revision, composition.transactions.getCommittedTransaction(proposed.transactionId)?.status],
    [2, "undone"]
  );

  assert.equal((await composition.module.execute("edit.redo", {
    documentId: "drawing:capabilities",
    expectedRevision: 2,
    approved: true
  }) as { revision: number }).revision, 3);
});

test("edit undo and redo return exact transaction metadata when the UI history limit is zero", async () => {
  const history = createCadEditHistory(snapshot(), 0);
  const composition = createEditCapabilityComposition(history);
  const proposed = await preview(composition, 0, 70);
  await composition.module.execute("edit.apply", {
    previewId: proposed.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
  });

  const undone = await composition.module.execute("edit.undo", {
    documentId: "drawing:capabilities", expectedRevision: 1, approved: true
  });
  const redone = await composition.module.execute("edit.redo", {
    documentId: "drawing:capabilities", expectedRevision: 2, approved: true
  });

  assert.deepEqual(undone, {
    documentId: "drawing:capabilities", revision: 2, transactionId: uuid(70), changeCount: 1
  });
  assert.deepEqual(redone, {
    documentId: "drawing:capabilities", revision: 3, transactionId: uuid(70), changeCount: 1
  });
  assert.deepEqual(history.entries(), []);
});

test("edit undo reports the exact transaction after it falls beyond one hundred UI entries", async () => {
  const history = createCadEditHistory(snapshot());
  const composition = createEditCapabilityComposition(history);
  for (let index = 0; index < 101; index += 1) {
    const proposed = await preview(composition, index, 200 + index);
    await composition.module.execute("edit.apply", {
      previewId: proposed.previewId,
      documentId: "drawing:capabilities",
      expectedRevision: index,
      approved: true
    });
  }
  assert.equal(history.entries().length, 100);

  let response: unknown;
  for (let index = 0; index < 101; index += 1) {
    response = await composition.module.execute("edit.undo", {
      documentId: "drawing:capabilities",
      expectedRevision: 101 + index,
      approved: true
    });
  }
  assert.deepEqual(response, {
    documentId: "drawing:capabilities", revision: 202, transactionId: uuid(200), changeCount: 1
  });
});

test("edit previews expire after ten minutes and retain at most twenty active previews per document", async () => {
  let now = 1_000;
  const composition = createEditCapabilityComposition(
    createCadEditHistory(snapshot()),
    { now: () => now }
  );
  const expiring = await preview(composition, 0, 8);
  now += 10 * 60 * 1000;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_EXPIRED"
  );

  const previews = [] as Awaited<ReturnType<typeof preview>>[];
  for (let index = 0; index < 21; index += 1) previews.push(await preview(composition, 0, 20 + index));
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: previews[0]!.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_EVICTED"
  );
  assert.equal((await composition.module.execute("edit.apply", {
    previewId: previews[20]!.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
  }) as { revision: number }).revision, 1);
});

test("active preview expiry precedes cross-document ownership checks at the TTL boundary", async () => {
  let now = 1_000;
  const composition = createEditCapabilityComposition(
    createCadEditHistory(snapshot()),
    { now: () => now }
  );
  const expiring = await preview(composition, 0, 85);

  now = 10 * 60 * 1000 + 999;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId,
      documentId: "drawing:other",
      expectedRevision: 0,
      approved: true
    }),
    (error) => codeOf(error) === "EDIT_DOCUMENT_MISMATCH"
  );

  now += 1;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId,
      documentId: "drawing:other",
      expectedRevision: 0,
      approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_EXPIRED"
  );
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId,
      documentId: "drawing:other",
      expectedRevision: 0,
      approved: true
    }),
    (error) => codeOf(error) === "EDIT_DOCUMENT_MISMATCH"
  );
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId,
      documentId: "drawing:capabilities",
      expectedRevision: 0,
      approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_EXPIRED"
  );

  now += 10 * 60 * 1000;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId,
      documentId: "drawing:other",
      expectedRevision: 0,
      approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_UNKNOWN"
  );
});

test("edit lifecycle tombstones expire and retain only the newest forty per document", async () => {
  let now = 1_000;
  const composition = createEditCapabilityComposition(
    createCadEditHistory(snapshot()),
    { now: () => now }
  );
  const expiring = await preview(composition, 0, 90);
  now += 10 * 60 * 1000;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_EXPIRED"
  );
  now += 10 * 60 * 1000;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_UNKNOWN"
  );

  const previews = [] as Awaited<ReturnType<typeof preview>>[];
  for (let index = 0; index < 61; index += 1) previews.push(await preview(composition, 0, 400 + index));
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: previews[0]!.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_UNKNOWN"
  );
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: previews[1]!.previewId, documentId: "drawing:capabilities", expectedRevision: 0, approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_EVICTED"
  );
});

test("expired lifecycle IDs are fully forgotten before cross-document disclosure checks", async () => {
  let now = 1_000;
  const composition = createEditCapabilityComposition(
    createCadEditHistory(snapshot()),
    { now: () => now }
  );
  const expiring = await preview(composition, 0, 95);
  now = 10 * 60 * 1000 + 1_000;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId,
      documentId: "drawing:capabilities",
      expectedRevision: 0,
      approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_EXPIRED"
  );

  now = 20 * 60 * 1000 + 1_000;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId,
      documentId: "drawing:other",
      expectedRevision: 0,
      approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_UNKNOWN"
  );

  now -= 1;
  await assert.rejects(
    () => composition.module.execute("edit.apply", {
      previewId: expiring.previewId,
      documentId: "drawing:capabilities",
      expectedRevision: 0,
      approved: true
    }),
    (error) => codeOf(error) === "EDIT_PREVIEW_UNKNOWN"
  );
});
