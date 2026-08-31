import assert from "node:assert/strict";
import { test } from "node:test";

import type { CadEntityIndex, CadEntityIndexItem } from "@dwg/contracts";
import { compareCadDrawings } from "@dwg/cad-query";

function entity(
  id: string,
  handle: string | null,
  type = "TEXT",
  layer = "A-TEXT",
  bbox: CadEntityIndexItem["bbox"] = { min: [0, 0, 0], max: [1, 1, 0] },
  text: string | null = "ROOM"
): CadEntityIndexItem {
  return {
    id, handle, type, layer, bbox, text,
    space: "model", layout: "Model", blockName: null,
    attributes: {}, geometry: {}, warnings: []
  };
}

function index(drawingId: string, entities: CadEntityIndexItem[]): CadEntityIndex {
  return {
    schemaVersion: "cad-index/v0.1", drawingId,
    source: { kind: "dxf", displayName: `${drawingId}.dxf`, parser: "fixture" },
    summary: { entityCount: entities.length, layerCount: 1, unsupportedCount: 0, modelSpaceCount: entities.length, paperSpaceCount: 0 },
    layers: [{ name: "A-TEXT", entityCount: entities.length, visible: true, frozen: false }],
    entities, unsupported: []
  };
}

test("compareCadDrawings matches non-null handles before stable IDs and returns deterministic changes", () => {
  const comparison = compareCadDrawings(
    index("before", [
      entity("stable-handle", "10", "TEXT", "A-OLD"),
      entity("same-id", null, "TEXT", "A-TEXT"),
      entity("removed", "30"),
      entity("handle-wins", "40", "TEXT", "A-TEXT", undefined, "before")
    ]),
    index("after", [
      entity("new-stable-handle", "10", "MTEXT", "A-NEW"),
      entity("same-id", null, "TEXT", "A-TEXT", undefined, "after"),
      entity("added", "20"),
      entity("handle-wins", "99", "TEXT", "A-TEXT", undefined, "ignored")
    ])
  );

  assert.deepEqual(comparison.added.map((match) => match.id), ["added"]);
  assert.deepEqual(comparison.removed.map((match) => match.id), ["removed"]);
  assert.deepEqual(comparison.changed.map((change) => [
    change.before.id,
    change.after.id,
    change.fields
  ]), [
    ["stable-handle", "new-stable-handle", ["type", "layer"]],
    ["handle-wins", "handle-wins", ["text"]],
    ["same-id", "same-id", ["text"]]
  ]);
});

test("compareCadDrawings treats bbox differences at or below one millionth as unchanged", () => {
  const before = index("before", [entity("stable", null)]);
  const withinTolerance = index("within", [entity(
    "stable", null, "TEXT", "A-TEXT",
    { min: [0.000001, 0, 0], max: [1, 1, 0] }
  )]);
  const outsideTolerance = index("outside", [entity(
    "stable", null, "TEXT", "A-TEXT",
    { min: [0.0000011, 0, 0], max: [1, 1, 0] }
  )]);

  assert.deepEqual(compareCadDrawings(before, withinTolerance).changed, []);
  assert.deepEqual(compareCadDrawings(before, outsideTolerance).changed.map((change) => change.fields), [["bbox"]]);
});

test("compareCadDrawings distinguishes null bounding boxes and orders additions removals by stable evidence", () => {
  const comparison = compareCadDrawings(
    index("before", [
      entity("z-removed", "z"),
      entity("a-removed", null),
      entity("stable", null, "TEXT", "A-TEXT", null)
    ]),
    index("after", [
      entity("z-added", "z2"),
      entity("a-added", null),
      entity("stable", null)
    ])
  );

  assert.deepEqual(comparison.added.map((match) => match.id), ["a-added", "z-added"]);
  assert.deepEqual(comparison.removed.map((match) => match.id), ["a-removed", "z-removed"]);
  assert.deepEqual(comparison.changed.map((change) => change.fields), [["bbox"]]);
});

test("compareCadDrawings normalizes forward-compatible bbox evidence", () => {
  const bbox = {
    min: [0, 0, 0] as [number, number, number],
    max: [1, 1, 0] as [number, number, number],
    extension: { source: "future" }
  };
  const comparison = compareCadDrawings(
    index("before", [entity("stable", "10", "TEXT", "A-TEXT", bbox, "before")]),
    index("after", [entity("stable", "10", "TEXT", "A-TEXT", bbox, "after")])
  );

  assert.deepEqual(comparison.changed[0]!.before.bbox, {
    min: [0, 0, 0],
    max: [1, 1, 0]
  });
  assert.deepEqual(Object.keys(comparison.changed[0]!.after.bbox!), ["min", "max"]);
});

test("compareCadDrawings accounts for repeated occurrences of the same entity object", () => {
  const repeated = entity("same", "10");
  const comparison = compareCadDrawings(
    index("before", [repeated, repeated]),
    index("after", [])
  );

  assert.equal(comparison.removed.length, 2);
  assert.deepEqual(comparison.removed.map((match) => match.id), ["same", "same"]);
});

test("compareCadDrawings rejects max plus one entities before comparison allocations", () => {
  const repeated = entity("same", "10");
  assert.throws(
    () => compareCadDrawings(
      index("before", Array(4_001).fill(repeated)),
      index("after", [])
    ),
    /input exceeds 4000 entities per drawing/
  );
});

test("compareCadDrawings rejects max plus one combined work occurrences", () => {
  const repeated = entity("same", "10");
  assert.throws(
    () => compareCadDrawings(
      index("before", Array(2_001).fill(repeated)),
      index("after", Array(2_000).fill(repeated))
    ),
    /work budget exceeds 4000 entity occurrences/
  );
});

test("compareCadDrawings pairs duplicate handles and IDs by stable occurrence order", () => {
  const comparison = compareCadDrawings(
    index("before", [
      entity("same-id", "10", "TEXT", "A-TEXT", undefined, "before-1"),
      entity("same-id", "10", "TEXT", "A-TEXT", undefined, "before-2"),
      entity("fallback-id", "20", "TEXT", "A-TEXT", undefined, "before-3"),
      entity("fallback-id", "21", "TEXT", "A-TEXT", undefined, "before-4")
    ]),
    index("after", [
      entity("same-id", "10", "TEXT", "A-TEXT", undefined, "after-1"),
      entity("same-id", "10", "TEXT", "A-TEXT", undefined, "after-2"),
      entity("fallback-id", "30", "TEXT", "A-TEXT", undefined, "after-3"),
      entity("fallback-id", "31", "TEXT", "A-TEXT", undefined, "after-4")
    ])
  );

  assert.deepEqual(comparison.changed.map((change) => [
    change.before.text,
    change.after.text
  ]), [
    ["before-1", "after-1"],
    ["before-2", "after-2"],
    ["before-3", "after-3"],
    ["before-4", "after-4"]
  ]);
});
