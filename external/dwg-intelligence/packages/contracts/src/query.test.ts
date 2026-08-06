import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isCadDrawingComparison,
  isCadSchedule,
  parseCadDrawingComparisonQuery,
  parseCadScheduleQuery
} from "@dwg/contracts";

test("query contracts accept only bounded serialized schedule and comparison DTOs", () => {
  assert.equal(isCadSchedule({
    rows: [{
      sourceHandles: ["10"],
      cells: ["ROOM"],
      layer: "A-TEXT",
      bbox: { min: [0, 0, 0], max: [1, 1, 0] }
    }]
  }), true);
  assert.equal(isCadSchedule({
    rows: [{ sourceHandles: ["10"], cells: ["ROOM"], layer: "A-TEXT", bbox: null, table: true }]
  }), false);
  assert.equal(isCadDrawingComparison({
    added: [],
    removed: [],
    changed: [{
      before: { id: "h:10", handle: "10", type: "TEXT", layer: "A-TEXT", bbox: null, reason: "comparison", confidence: 1 },
      after: { id: "h:10", handle: "10", type: "TEXT", layer: "A-TEXT", bbox: null, reason: "comparison", confidence: 1 },
      fields: ["text"]
    }]
  }), true);
  assert.equal(isCadDrawingComparison({ added: [], removed: [], changed: [], extra: true }), false);
  assert.equal(isCadDrawingComparison({
    added: [], removed: [], changed: [{
      before: { id: "h:10", handle: "10", type: "TEXT", layer: "A-TEXT", bbox: null, reason: "comparison", confidence: 1 },
      after: { id: "h:10", handle: "10", type: "TEXT", layer: "A-TEXT", bbox: null, reason: "comparison", confidence: 1 },
      fields: ["text", "text"]
    }]
  }), false);
});

test("query contracts reject malformed capability inputs before a drawing lookup", () => {
  const matches = [{
    id: "h:10",
    handle: "10",
    type: "TEXT",
    layer: "A-TEXT",
    bbox: { min: [0, 0, 0], max: [1, 1, 0] },
    text: "ROOM",
    reason: "text contains query",
    confidence: 1
  }];
  assert.deepEqual(parseCadScheduleQuery({
    drawingId: "before",
    matches,
    yTolerance: 0.25
  }), {
    drawingId: "before", matches, yTolerance: 0.25
  });
  assert.deepEqual(parseCadDrawingComparisonQuery({ beforeDrawingId: "before", afterDrawingId: "after" }), {
    beforeDrawingId: "before", afterDrawingId: "after"
  });
  assert.throws(
    () => parseCadScheduleQuery({ drawingId: "before", matches, yTolerance: 0 }),
    /Invalid CAD schedule query/
  );
  assert.throws(
    () => parseCadScheduleQuery({ drawingId: "before", yTolerance: 0.25 }),
    /Invalid CAD schedule query/
  );
  assert.throws(() => parseCadDrawingComparisonQuery({ beforeDrawingId: "before", afterDrawingId: "after", extra: true }), /Invalid CAD drawing comparison query/);
});
