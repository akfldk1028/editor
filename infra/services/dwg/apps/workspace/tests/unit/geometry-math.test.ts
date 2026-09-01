import assert from "node:assert/strict";
import test from "node:test";

import {
  arcPath,
  bulgeSegment,
  isPlanarNormal,
  polylinePath
} from "../../src/features/cad-viewer/geometry/geometryMath.js";

test("arc path uses actual endpoints and large-arc sweep", () => {
  assert.equal(
    arcPath({
      kind: "arc",
      center: [0, 0, 0],
      radius: 10,
      startAngle: 0,
      endAngle: Math.PI * 1.5,
      normal: [0, 0, 1]
    }),
    "M 10 0 A 10 10 0 1 1 0 -10"
  );
});

test("negative-Z arc reverses the sweep without changing endpoints", () => {
  assert.equal(
    arcPath({
      kind: "arc",
      center: [0, 0, 0],
      radius: 10,
      startAngle: 0,
      endAngle: Math.PI / 2,
      normal: [0, 0, -1]
    }),
    "M 10 0 A 10 10 0 0 0 0 10"
  );
});

test("bulge one produces a semicircle instead of a line", () => {
  assert.deepEqual(
    bulgeSegment([0, 0, 0], [10, 0, 0], 1),
    {
      radius: 5,
      largeArc: 0,
      sweep: 1
    }
  );
});

test("closed polyline emits its final segment", () => {
  assert.equal(
    polylinePath({
      kind: "lwpolyline",
      vertices: [
        {
          point: [0, 0, 0],
          bulge: 0,
          startWidth: 0,
          endWidth: 0
        },
        {
          point: [10, 0, 0],
          bulge: 0,
          startWidth: 0,
          endWidth: 0
        },
        {
          point: [10, 10, 0],
          bulge: 0,
          startWidth: 0,
          endWidth: 0
        }
      ],
      closed: true,
      elevation: 0,
      normal: [0, 0, 1]
    }),
    "M 0 0 L 10 0 L 10 10 L 0 0 Z"
  );
});

test("rejects non-planar and non-finite geometry", () => {
  assert.equal(isPlanarNormal([1, 0, 0]), false);
  assert.equal(isPlanarNormal([0, 0, -1]), true);
  assert.equal(
    arcPath({
      kind: "arc",
      center: [0, 0, 0],
      radius: Number.NaN,
      startAngle: 0,
      endAngle: Math.PI,
      normal: [0, 0, 1]
    }),
    null
  );
});
