import assert from "node:assert/strict";
import test from "node:test";

import { isCadEntityIndex } from "../src/index.js";

test("accepts legacy v0.1 and v0.2 indexes that omit additive drawing and layer metadata", () => {
  for (const schemaVersion of ["cad-index/v0.1", "cad-index/v0.2"] as const) {
    const index = {
      schemaVersion,
      drawingId: "legacy",
      source: { kind: "dxf", displayName: "legacy.dxf", parser: "test" },
      summary: {
        entityCount: 1,
        layerCount: 1,
        unsupportedCount: 0,
        modelSpaceCount: 1,
        paperSpaceCount: 0
      },
      layers: [{ name: "0", entityCount: 1, visible: true, frozen: false }],
      unsupported: [],
      entities: [
        {
          id: "h:1",
          handle: "1",
          type: "POINT",
          layer: "0",
          space: "model",
          layout: "Model",
          bbox: { min: [0, 0, 0], max: [0, 0, 0] },
          text: null,
          blockName: null,
          attributes: {},
          warnings: [],
          geometry: schemaVersion === "cad-index/v0.1"
            ? {}
            : { kind: "point", position: [0, 0, 0] }
        }
      ]
    };

    assert.equal(isCadEntityIndex(index), true);
  }
});

test("rejects malformed optional drawing and layer metadata when supplied", () => {
  const index = {
    schemaVersion: "cad-index/v0.2",
    drawingId: "invalid-metadata",
    source: { kind: "dwg", displayName: "invalid.dwg", parser: "test" },
    summary: { entityCount: 1, layerCount: 1, unsupportedCount: 0, modelSpaceCount: 1, paperSpaceCount: 0 },
    drawing: { fileVersion: null, units: 42 },
    layers: [{ name: "0", entityCount: 1, visible: true, frozen: false, color: "red", locked: false }],
    unsupported: [],
    entities: [{
      id: "h:1", handle: "1", type: "POINT", layer: "0", space: "model", layout: "Model",
      bbox: { min: [0, 0, 0], max: [0, 0, 0] }, text: null, blockName: null, attributes: {}, warnings: [],
      geometry: { kind: "point", position: [0, 0, 0] }
    }]
  };

  assert.equal(isCadEntityIndex(index), false);
});
