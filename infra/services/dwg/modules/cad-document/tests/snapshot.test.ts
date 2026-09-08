import assert from "node:assert/strict";
import test from "node:test";

import type { CadEntityIndex, CadEntityIndexV01 } from "@dwg/contracts";
import {
  cloneDocumentSnapshot,
  createDocumentSnapshot,
  normalizeEditableIndex
} from "../src/index.js";

const sourceSha256 = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899";

test("normalizes legacy entities into explicit editable v0.2 evidence", () => {
  const normalized = normalizeEditableIndex(legacyIndex());

  assert.equal(normalized.schemaVersion, "cad-index/v0.2");
  assert.deepEqual(normalized.entities.map((entity) => entity.geometry), [
    { kind: "bbox", reason: "legacy-v0.1" },
    { kind: "unavailable", reason: "legacy-v0.1-no-bbox" }
  ]);
});

test("creates a null-preserving snapshot with deterministic imported layer IDs", () => {
  const snapshot = createDocumentSnapshot(legacyIndex(), sourceSha256.toLowerCase());

  assert.deepEqual(snapshot, {
    documentId: "legacy-drawing",
    revision: 0,
    sourceSha256: sourceSha256.toUpperCase(),
    drawingVersion: null,
    units: null,
    index: normalizeEditableIndex(legacyIndex()),
    layers: [
      {
        id: "layer:imported:QS1UQUc",
        name: "A-TAG",
        color: null,
        visible: true,
        frozen: false,
        locked: null
      },
      {
        id: "layer:imported:67K9",
        name: "벽",
        color: null,
        visible: false,
        frozen: true,
        locked: null
      }
    ]
  });
});

test("normalizes omitted v0.2 layer evidence to null without changing explicit false", () => {
  const index = structuredClone(legacyIndex()) as CadEntityIndex;
  index.schemaVersion = "cad-index/v0.2";
  index.entities = index.entities.map((entity) => ({
    ...entity,
    geometry: { kind: "bbox", reason: "test" }
  }));
  index.layers[0] = {
    ...index.layers[0],
    color: 90,
    locked: false
  };

  const snapshot = createDocumentSnapshot(index, sourceSha256);

  assert.deepEqual(snapshot.index.drawing, {
    fileVersion: null,
    units: null
  });
  assert.deepEqual(snapshot.layers, [
    {
      id: "layer:imported:QS1UQUc",
      name: "A-TAG",
      color: 90,
      visible: true,
      frozen: false,
      locked: false
    },
    {
      id: "layer:imported:67K9",
      name: legacyIndex().layers[1].name,
      color: null,
      visible: false,
      frozen: true,
      locked: null
    }
  ]);
});

test("propagates supplied v0.2 drawing metadata to snapshot fields", () => {
  const index = structuredClone<CadEntityIndex>(legacyIndex());
  index.schemaVersion = "cad-index/v0.2";
  if (index.schemaVersion !== "cad-index/v0.2") {
    assert.fail("Expected the metadata fixture to be cad-index/v0.2.");
  }
  index.drawing = {
    fileVersion: "AC1032",
    units: "Millimeters"
  };
  index.entities = index.entities.map((entity) => ({
    ...entity,
    geometry: { kind: "bbox", reason: "test" }
  }));

  const snapshot = createDocumentSnapshot(index, sourceSha256);

  assert.equal(snapshot.drawingVersion, "AC1032");
  assert.equal(snapshot.units, "Millimeters");
});

test("rejects source hashes that are not SHA-256 digests", () => {
  assert.throws(
    () => createDocumentSnapshot(legacyIndex(), "not-a-sha256"),
    /sha-256/i
  );
});

test("rejects duplicate non-null entity handles", () => {
  const index = legacyIndex();
  index.entities[1].handle = "AB";

  assert.throws(() => createDocumentSnapshot(index, sourceSha256), /duplicate.*handle/i);
});

test("rejects non-finite editable geometry", () => {
  const index = structuredClone(legacyIndex()) as CadEntityIndex;
  index.schemaVersion = "cad-index/v0.2";
  index.entities = [{
    ...index.entities[0],
    geometry: { kind: "point", position: [Number.NaN, 0, 0] }
  }];

  assert.throws(() => createDocumentSnapshot(index, sourceSha256), /finite/i);
});

test("cloning a snapshot isolates editable nested state", () => {
  const source = createDocumentSnapshot(legacyIndex(), sourceSha256);
  const clone = cloneDocumentSnapshot(source);

  clone.layers[0].name = "RENAMED";
  clone.index.entities[0].attributes.status = "edited";

  assert.equal(source.layers[0].name, "A-TAG");
  assert.equal(source.index.entities[0].attributes.status, undefined);
});

function legacyIndex(): CadEntityIndexV01 {
  return {
    schemaVersion: "cad-index/v0.1",
    drawingId: "legacy-drawing",
    source: { kind: "dxf", displayName: "legacy.dxf", parser: "test" },
    summary: {
      entityCount: 2,
      layerCount: 2,
      unsupportedCount: 0,
      modelSpaceCount: 2,
      paperSpaceCount: 0
    },
    layers: [
      { name: "A-TAG", entityCount: 1, visible: true, frozen: false },
      { name: "벽", entityCount: 1, visible: false, frozen: true }
    ],
    unsupported: [],
    entities: [
      {
        id: "h:AB",
        handle: "AB",
        type: "TEXT",
        layer: "A-TAG",
        space: "model",
        layout: "Model",
        bbox: { min: [0, 0, 0], max: [10, 5, 0] },
        text: "ROOM 101",
        blockName: null,
        attributes: {},
        warnings: [],
        geometry: {}
      },
      {
        id: "e:1",
        handle: null,
        type: "HATCH",
        layer: "벽",
        space: "model",
        layout: "Model",
        bbox: null,
        text: null,
        blockName: null,
        attributes: {},
        warnings: ["bbox-unavailable"],
        geometry: {}
      }
    ]
  };
}
