import assert from "node:assert/strict";
import { test } from "node:test";

import type { CadEntityIndex } from "@dwg/contracts";

import {
  composeCadCapabilityModules,
  createReadCapabilityModule,
  type CadCapabilityModule
} from "@dwg/cad-capabilities";

test("read capability module returns deterministic index evidence", async () => {
  const index: CadEntityIndex = {
    schemaVersion: "cad-index/v0.1",
    drawingId: "fixture-drawing",
    source: { kind: "dxf", displayName: "fixture.dxf", parser: "fixture" },
    summary: {
      entityCount: 1,
      layerCount: 1,
      unsupportedCount: 0,
      modelSpaceCount: 1,
      paperSpaceCount: 0
    },
    layers: [{ name: "A-TEXT", entityCount: 1, visible: true, frozen: false }],
    entities: [{
      id: "h:10",
      handle: "10",
      type: "TEXT",
      layer: "A-TEXT",
      space: "model",
      layout: "Model",
      bbox: { min: [0, 0, 0], max: [1, 1, 0] },
      text: "ROOM 101",
      blockName: null,
      attributes: {},
      geometry: {},
      warnings: []
    }],
    unsupported: []
  };
  const capabilities = createReadCapabilityModule({
    async open(path) {
      assert.equal(path, "fixture.dxf");
      return index;
    },
    get(drawingId) {
      return drawingId === index.drawingId ? index : null;
    }
  });

  const opened = await capabilities.execute("document.open", { path: "fixture.dxf" }) as {
    drawingId: string;
  };
  assert.equal(opened.drawingId, "fixture-drawing");

  const layers = await capabilities.execute("query.layers", {
    drawingId: opened.drawingId
  }) as { layers: Array<{ name: string }> };
  assert.deepEqual(layers.layers, index.layers);

  const text = await capabilities.execute("query.text", {
    drawingId: opened.drawingId,
    query: "ROOM"
  }) as { matches: Array<{ handle: string | null }> };
  assert.deepEqual(text.matches.map((match) => match.handle), ["10"]);

  const description = await capabilities.execute("document.describe", {
    drawingId: opened.drawingId
  }) as { unsupported: unknown[] };
  assert.deepEqual(description.unsupported, []);
});

test("composer routes through a named module with the exact AbortSignal", async () => {
  const controller = new AbortController();
  let receivedSignal: AbortSignal | undefined;
  const module: CadCapabilityModule = {
    names: ["query.layers"],
    async execute(name, input, signal) {
      assert.equal(name, "query.layers");
      assert.deepEqual(input, { drawingId: "fixture" });
      receivedSignal = signal;
      return { layers: [] };
    }
  };

  const runtime = composeCadCapabilityModules([module]);
  assert.deepEqual(
    await runtime.execute("query.layers", { drawingId: "fixture" }, controller.signal),
    { layers: [] }
  );
  assert.equal(receivedSignal, controller.signal);
});

test("composer rejects duplicate and unknown capability names", async () => {
  const module: CadCapabilityModule = {
    names: ["query.layers"],
    async execute() {
      return { layers: [] };
    }
  };

  assert.throws(
    () => composeCadCapabilityModules([module, module]),
    /Duplicate CAD capability name: query\.layers/
  );

  const runtime = composeCadCapabilityModules([module]);
  await assert.rejects(
    () => runtime.execute("query.text", { drawingId: "fixture", query: "ROOM" }),
    /Unknown CAD capability: query\.text/
  );
});

test("read capability module exposes bounded grounded schedule and comparison queries", async () => {
  const before: CadEntityIndex = {
    schemaVersion: "cad-index/v0.1",
    drawingId: "before",
    source: { kind: "dxf", displayName: "before.dxf", parser: "fixture" },
    summary: { entityCount: 1, layerCount: 1, unsupportedCount: 0, modelSpaceCount: 1, paperSpaceCount: 0 },
    layers: [{ name: "A-TEXT", entityCount: 1, visible: true, frozen: false }],
    entities: [{
      id: "h:10", handle: "10", type: "TEXT", layer: "A-TEXT", space: "model", layout: "Model",
      bbox: { min: [0, 0, 0], max: [1, 1, 0] }, text: "BEFORE", blockName: null,
      attributes: {}, geometry: {}, warnings: []
    }],
    unsupported: []
  };
  const after: CadEntityIndex = {
    ...before,
    drawingId: "after",
    entities: [{ ...before.entities[0]!, text: "AFTER" }]
  };
  const capabilities = createReadCapabilityModule({
    async open() { return before; },
    get(drawingId) { return drawingId === "before" ? before : drawingId === "after" ? after : null; }
  });

  assert.deepEqual(await capabilities.execute("query.schedule", {
    drawingId: "before",
    matches: [{
      id: "h:10", handle: "10", type: "TEXT", layer: "A-TEXT",
      bbox: { min: [0, 0, 0], max: [1, 1, 0] }, text: "BEFORE",
      reason: "text contains query", confidence: 1
    }],
    yTolerance: 0.5
  }), {
    rows: [{
      sourceHandles: ["10"], cells: ["BEFORE"], layer: "A-TEXT",
      bbox: { min: [0, 0, 0], max: [1, 1, 0] }
    }]
  });
  assert.deepEqual(await capabilities.execute("query.schedule", {
    drawingId: "before", matches: [], yTolerance: 0.5
  }), {
    rows: []
  });
  assert.deepEqual(await capabilities.execute("query.compare", {
    beforeDrawingId: "before", afterDrawingId: "after"
  }), {
    added: [], removed: [], changed: [{
      before: {
        id: "h:10", handle: "10", type: "TEXT", layer: "A-TEXT",
        bbox: { min: [0, 0, 0], max: [1, 1, 0] }, text: "BEFORE",
        reason: "matched drawing evidence", confidence: 1
      },
      after: {
        id: "h:10", handle: "10", type: "TEXT", layer: "A-TEXT",
        bbox: { min: [0, 0, 0], max: [1, 1, 0] }, text: "AFTER",
        reason: "matched drawing evidence", confidence: 1
      },
      fields: ["text"]
    }]
  });
});

test("read capability module rejects a pre-aborted grounded query", async () => {
  const controller = new AbortController();
  controller.abort();
  const capabilities = createReadCapabilityModule({
    async open() { throw new Error("not called"); },
    get() { throw new Error("not called"); }
  });

  await assert.rejects(
    () => capabilities.execute(
      "query.schedule",
      { drawingId: "fixture", matches: [], yTolerance: 1 },
      controller.signal
    ),
    /CAD read operation was cancelled/
  );
});

test("read capability module rejects when a grounded query aborts during lookup", async () => {
  const controller = new AbortController();
  const index: CadEntityIndex = {
    schemaVersion: "cad-index/v0.1",
    drawingId: "fixture",
    source: { kind: "dxf", displayName: "fixture.dxf", parser: "fixture" },
    summary: { entityCount: 0, layerCount: 0, unsupportedCount: 0, modelSpaceCount: 0, paperSpaceCount: 0 },
    layers: [], entities: [], unsupported: []
  };
  const capabilities = createReadCapabilityModule({
    async open() { throw new Error("not called"); },
    get() {
      controller.abort();
      return index;
    }
  });

  await assert.rejects(
    () => capabilities.execute(
      "query.schedule",
      { drawingId: "fixture", matches: [], yTolerance: 1 },
      controller.signal
    ),
    /CAD read operation was cancelled/
  );
});

test("comparison capability stops before the second lookup after cancellation", async () => {
  const controller = new AbortController();
  let lookups = 0;
  const index: CadEntityIndex = {
    schemaVersion: "cad-index/v0.1",
    drawingId: "fixture",
    source: { kind: "dxf", displayName: "fixture.dxf", parser: "fixture" },
    summary: { entityCount: 0, layerCount: 0, unsupportedCount: 0, modelSpaceCount: 0, paperSpaceCount: 0 },
    layers: [], entities: [], unsupported: []
  };
  const capabilities = createReadCapabilityModule({
    async open() { throw new Error("not called"); },
    get() {
      lookups += 1;
      controller.abort();
      return index;
    }
  });

  await assert.rejects(
    () => capabilities.execute(
      "query.compare",
      { beforeDrawingId: "before", afterDrawingId: "after" },
      controller.signal
    ),
    /CAD read operation was cancelled/
  );
  assert.equal(lookups, 1);
});
