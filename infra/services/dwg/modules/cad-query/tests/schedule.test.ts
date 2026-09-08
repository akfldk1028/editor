import assert from "node:assert/strict";
import { test } from "node:test";

import type { CadEntityIndex, CadEntityIndexItem } from "@dwg/contracts";
import { extractCadSchedule } from "@dwg/cad-query";

function entity(
  id: string,
  type: string,
  text: string | null,
  bbox: CadEntityIndexItem["bbox"],
  handle: string | null = id
): CadEntityIndexItem {
  return {
    id,
    handle,
    type,
    layer: "A-TEXT",
    space: "model",
    layout: "Model",
    bbox,
    text,
    blockName: null,
    attributes: {},
    geometry: {},
    warnings: []
  };
}

function index(entities: CadEntityIndexItem[]): CadEntityIndex {
  return {
    schemaVersion: "cad-index/v0.1",
    drawingId: "fixture",
    source: { kind: "dxf", displayName: "fixture.dxf", parser: "fixture" },
    summary: {
      entityCount: entities.length,
      layerCount: 1,
      unsupportedCount: 0,
      modelSpaceCount: entities.length,
      paperSpaceCount: 0
    },
    layers: [{ name: "A-TEXT", entityCount: entities.length, visible: true, frozen: false }],
    entities,
    unsupported: []
  };
}

test("extractCadSchedule groups TEXT and MTEXT into Y bands then sorts cells by X", () => {
  const schedule = extractCadSchedule(index([
    entity("h:20", "MTEXT", "B", { min: [20, 10.0005, 0], max: [22, 11, 0] }, "20"),
    entity("h:10", "TEXT", "A", { min: [10, 10, 0], max: [12, 11, 0] }, "10"),
    entity("h:30", "TEXT", "C", { min: [10, 5, 0], max: [12, 6, 0] }, "30"),
    entity("h:40", "LINE", null, { min: [0, 0, 0], max: [1, 1, 0] }, "40")
  ]), { yTolerance: 0.001 });

  assert.deepEqual(schedule, {
    rows: [
      {
        sourceHandles: ["10", "20"],
        cells: ["A", "B"],
        layer: "A-TEXT",
        bbox: { min: [10, 10, 0], max: [22, 11, 0] }
      },
      {
        sourceHandles: ["30"],
        cells: ["C"],
        layer: "A-TEXT",
        bbox: { min: [10, 5, 0], max: [12, 6, 0] }
      }
    ]
  });
});

test("extractCadSchedule preserves duplicate text and only includes located TEXT or MTEXT evidence", () => {
  const schedule = extractCadSchedule(index([
    entity("h:11", "TEXT", "ROOM", { min: [0, 0, 0], max: [1, 1, 0] }, "11"),
    entity("h:12", "TEXT", "ROOM", { min: [2, 0, 0], max: [3, 1, 0] }, "12"),
    entity("h:13", "MTEXT", "unlocated", null, "13"),
    entity("h:14", "TEXT", null, { min: [4, 0, 0], max: [5, 1, 0] }, "14")
  ]));

  assert.deepEqual(schedule.rows, [{
    sourceHandles: ["11", "12"],
    cells: ["ROOM", "ROOM"],
    layer: "A-TEXT",
    bbox: { min: [0, 0, 0], max: [3, 1, 0] }
  }]);
});

test("extractCadSchedule returns a serialized empty row set when no positioned text exists", () => {
  assert.deepEqual(extractCadSchedule(index([])), { rows: [] });
});

test("extractCadSchedule keeps distinct layer evidence out of the same Y band", () => {
  const schedule = extractCadSchedule(index([
    entity("h:10", "TEXT", "A1", { min: [0, 10, 0], max: [1, 11, 0] }, "10"),
    { ...entity("h:20", "TEXT", "B1", { min: [0, 10, 0], max: [1, 11, 0] }, "20"), layer: "B-TEXT" },
    entity("h:11", "TEXT", "A2", { min: [2, 9.9, 0], max: [3, 10.9, 0] }, "11")
  ]), { yTolerance: 0.2 });

  assert.deepEqual(schedule.rows.map((row) => [row.layer, row.cells]), [
    ["A-TEXT", ["A1", "A2"]],
    ["B-TEXT", ["B1"]]
  ]);
});

test("extractCadSchedule normalizes forward-compatible bbox evidence", () => {
  const bbox = {
    min: [0, 0, 0] as [number, number, number],
    max: [1, 1, 0] as [number, number, number],
    extension: { source: "future" }
  };

  const schedule = extractCadSchedule(index([
    entity("h:10", "TEXT", "ROOM", bbox, "10")
  ]));

  assert.deepEqual(schedule.rows[0]!.bbox, {
    min: [0, 0, 0],
    max: [1, 1, 0]
  });
  assert.deepEqual(Object.keys(schedule.rows[0]!.bbox!), ["min", "max"]);
});
