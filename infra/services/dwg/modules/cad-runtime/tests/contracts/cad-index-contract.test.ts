import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import {
  isCadEntityIndex,
  isCadEntityIndexV02
} from "@dwg/contracts";
import { createCadApplication } from "../../src/application/createCadApplication.js";

const require = createRequire(import.meta.url);
const Ajv2020 = require("ajv/dist/2020").default as typeof import(
  "ajv/dist/2020.js"
).default;

const base = {
  drawingId: "dwg:test",
  source: {
    kind: "dwg",
    displayName: "test.dwg",
    parser: "acadsharp@3.6.35"
  },
  summary: {
    entityCount: 1,
    layerCount: 1,
    unsupportedCount: 0,
    modelSpaceCount: 1,
    paperSpaceCount: 0
  },
  layers: [
    {
      name: "0",
      entityCount: 1,
      visible: true,
      frozen: false
    }
  ],
  unsupported: []
};

const lineV02 = {
  ...base,
  schemaVersion: "cad-index/v0.2",
  entities: [
    {
      id: "h:1",
      handle: "1",
      type: "LINE",
      layer: "0",
      space: "model",
      layout: "Model",
      bbox: {
        min: [0, 0, 0],
        max: [10, 5, 0]
      },
      text: null,
      blockName: null,
      attributes: {},
      geometry: {
        kind: "line",
        start: [0, 0, 0],
        end: [10, 5, 0]
      },
      warnings: []
    }
  ]
};

test("accepts strict v0.2 and identifies typed geometry", () => {
  assert.equal(isCadEntityIndex(lineV02), true);
  assert.equal(isCadEntityIndexV02(lineV02), true);
});

test("retains v0.1 input compatibility", () => {
  const legacy = {
    ...lineV02,
    schemaVersion: "cad-index/v0.1",
    entities: [
      {
        ...lineV02.entities[0],
        geometry: {}
      }
    ]
  };

  assert.equal(isCadEntityIndex(legacy), true);
  assert.equal(isCadEntityIndexV02(legacy), false);
});

test("rejects malformed v0.2 geometry", () => {
  assert.equal(
    isCadEntityIndex({
      ...lineV02,
      entities: [
        {
          ...lineV02.entities[0],
          geometry: {
            kind: "line",
            start: [0, 0],
            end: [10, 5, 0]
          }
        }
      ]
    }),
    false
  );
  assert.equal(
    isCadEntityIndex({
      ...lineV02,
      entities: [
        {
          ...lineV02.entities[0],
          geometry: {
            kind: "invented",
            value: 1
          }
        }
      ]
    }),
    false
  );
});

test("JSON Schema and shared validator agree", () => {
  const schema = JSON.parse(
    readFileSync("modules/cad-runtime/contracts/cad-index.schema.json", "utf8")
  );
  const validate = new Ajv2020({ strict: true }).compile(schema);

  assert.equal(validate(lineV02), true);
  assert.equal(validate({
    ...lineV02,
    schemaVersion: "cad-index/v9"
  }), false);
});

test("optional drawing revision is additive, strict, and shared by JSON Schema and validator", () => {
  const schema = JSON.parse(
    readFileSync("modules/cad-runtime/contracts/cad-index.schema.json", "utf8")
  );
  const validate = new Ajv2020({ strict: true }).compile(schema);
  const revised = {
    ...lineV02,
    drawing: {
      fileVersion: "AC1032",
      units: "Millimeters",
      revision: 3
    }
  };

  assert.equal(isCadEntityIndex(revised), true);
  assert.equal(validate(revised), true);

  for (const revision of [-1, 1.5, "3"]) {
    const invalid = {
      ...revised,
      drawing: { ...revised.drawing, revision }
    };
    assert.equal(isCadEntityIndex(invalid), false);
    assert.equal(validate(invalid), false);
  }

  const extraDrawingKey = {
    ...revised,
    drawing: { ...revised.drawing, implementationDetail: "leak" }
  };
  assert.equal(isCadEntityIndex(extraDrawingKey), false);
  assert.equal(validate(extraDrawingKey), false);

  assert.equal(isCadEntityIndex(lineV02), true);
  assert.equal(validate(lineV02), true);
});

test("edited application snapshots remain valid cad-index documents", async () => {
  const application = await createCadApplication({
    loadInitialIndex: async () => lineV02,
    sourceSha256: "a".repeat(64)
  });
  const preview = await application.capabilities.execute("edit.preview", {
    batch: {
      schemaVersion: "cad-edit/v1",
      transactionId: "44444444-4444-4444-8444-444444444444",
      documentId: "dwg:test",
      expectedRevision: 0,
      commands: [{
        commandId: "55555555-5555-4555-8555-555555555555",
        expectedRevision: 0,
        origin: { kind: "user", id: "schema-test" },
        preconditions: [{ target: "1", field: "exists", equals: true }],
        operation: { kind: "entity.move", handles: ["1"], delta: [5, 0, 0] }
      }]
    }
  }) as { previewId: string };
  await application.capabilities.execute("edit.apply", {
    previewId: preview.previewId,
    documentId: "dwg:test",
    expectedRevision: 0,
    approved: true
  });

  const edited = application.currentIndex();
  const schema = JSON.parse(
    readFileSync("modules/cad-runtime/contracts/cad-index.schema.json", "utf8")
  );
  const validate = new Ajv2020({ strict: true }).compile(schema);
  assert.equal(isCadEntityIndex(edited), true);
  assert.equal(validate(edited), true, JSON.stringify(validate.errors));
  assert.equal(edited.drawing?.revision, 1);
  assert.deepEqual(edited.entities[0]?.bbox, {
    min: [5, 0, 0],
    max: [15, 5, 0]
  });
});
