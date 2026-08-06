import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { createCadToolRuntime } from "../src/application/cad-tools/runtime.js";
import { createCadApplication } from "../src/application/createCadApplication.js";
import { buildIndexFromDxfText } from "../src/parsers/dxf/dxfIndexer.js";

const dxfFixture = "tests/fixtures/dxf/minimal-architectural.dxf";

test("builds a metadata-bearing cad-index/v0.2 entity index from a DXF fixture", async () => {
  const dxfText = await readFile(dxfFixture, "utf8");

  const index = buildIndexFromDxfText(dxfText, {
    displayName: "minimal-architectural.dxf"
  });

  assert.equal(index.schemaVersion, "cad-index/v0.2");
  assert.equal(index.drawing?.fileVersion, "AC1027");
  assert.equal(index.source.kind, "dxf");
  assert.ok(index.summary.entityCount >= 4);
  assert.ok(index.layers.some((layer) => layer.name === "A-WALL"));
  assert.ok(index.entities.some((entity) => entity.layer === "A-WALL" && entity.type === "LINE"));
});

test("DXF text roundtrip preserves deterministic evidence when the writer adds a zero alignment point", async () => {
  const source = await readFile(dxfFixture, "utf8");
  const writerRepresentation = source.replace(
    "40\n250\n1\nROOM 101",
    "40\n250\n11\n0\n21\n0\n31\n0\n1\nROOM 101"
  );
  const before = buildIndexFromDxfText(source).entities.find((entity) => entity.handle === "30");
  const reopened = buildIndexFromDxfText(writerRepresentation).entities.find((entity) => entity.handle === "30");

  assert.ok(before && reopened);
  assert.deepEqual(
    {
      handle: reopened.handle,
      layer: reopened.layer,
      type: reopened.type,
      bbox: reopened.bbox
    },
    {
      handle: before.handle,
      layer: before.layer,
      type: before.type,
      bbox: before.bbox
    }
  );
});

test("finds layer matches with stable IDs, handles, layer, type, and bbox", async () => {
  const application = await createCadApplication();
  const runtime = createCadToolRuntime(application.capabilities);
  const opened = await runtime.call("cad.open_drawing", {
    path: dxfFixture
  });
  await runtime.call("cad.build_index", { drawingId: opened.drawingId });

  const result = await runtime.call("cad.find_entities_by_layer", {
    drawingId: opened.drawingId,
    layer: "A-WALL"
  });

  assert.ok(result.matches.length >= 2);
  for (const match of result.matches) {
    assert.equal(match.layer, "A-WALL");
    assert.ok(match.id);
    assert.ok(match.handle);
    assert.ok(match.type);
    assert.ok(match.bbox);
  }
});

test("keeps drawingId available after building an index for harness chaining", async () => {
  const application = await createCadApplication();
  const runtime = createCadToolRuntime(application.capabilities);
  const opened = await runtime.call("cad.open_drawing", {
    path: dxfFixture
  });

  const built = await runtime.call("cad.build_index", { drawingId: opened.drawingId });

  assert.equal(built.drawingId, opened.drawingId);
  assert.ok(built.indexUri.includes(opened.drawingId));
});

test("finds text matches without asking the model to inspect geometry", async () => {
  const application = await createCadApplication();
  const runtime = createCadToolRuntime(application.capabilities);
  const opened = await runtime.call("cad.open_drawing", {
    path: dxfFixture
  });
  await runtime.call("cad.build_index", { drawingId: opened.drawingId });

  const result = await runtime.call("cad.find_text", {
    drawingId: opened.drawingId,
    query: "ROOM"
  });

  assert.equal(result.matches.length, 1);
  assert.equal(result.matches[0].text, "ROOM 101");
  assert.equal(result.matches[0].layer, "A-TEXT");
});
