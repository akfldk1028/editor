import assert from "node:assert/strict";
import { test } from "node:test";

import { verifyMatches } from "../../src/orchestration/evidenceVerifier.js";

test("accepts CAD matches with complete stable evidence", () => {
  const accepted = verifyMatches([
    {
      id: "h:10",
      handle: "10",
      type: "LINE",
      layer: "A-WALL",
      bbox: { min: [0, 0, 0], max: [1000, 0, 0] },
      reason: "layer equals query",
      confidence: 1
    }
  ]);

  assert.equal(accepted.status, "accepted");
  assert.equal(accepted.matches.length, 1);
  assert.deepEqual(accepted.issues, []);
});

test("rejects matches with missing handles or bounding boxes", () => {
  const rejected = verifyMatches([
    {
      id: "h:10",
      handle: null,
      type: "LINE",
      layer: "A-WALL",
      bbox: null,
      reason: "layer equals query",
      confidence: 0.5
    }
  ]);

  assert.equal(rejected.status, "rejected");
  assert.deepEqual(rejected.matches, []);
  assert.deepEqual(rejected.issues, [
    { entityId: "h:10", missing: ["handle", "bbox"] }
  ]);
});

test("reports every invalid match instead of stopping at the first", () => {
  const rejected = verifyMatches([
    {
      id: "",
      handle: "10",
      type: "",
      layer: "A-WALL",
      bbox: { min: [0, 0, 0], max: [1, 1, 0] },
      reason: "invalid fixture",
      confidence: 0.5
    },
    {
      id: "h:11",
      handle: null,
      type: "LINE",
      layer: "",
      bbox: null,
      reason: "invalid fixture",
      confidence: 0.5
    }
  ]);

  assert.deepEqual(rejected.issues, [
    { entityId: "(missing-id)", missing: ["id", "type"] },
    { entityId: "h:11", missing: ["handle", "layer", "bbox"] }
  ]);
});
