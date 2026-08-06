import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";

import {
  buildCadIndexForPath,
  createCadToolRuntime
} from "../../src/application/cad-tools/runtime.js";
import { createCadApplication } from "../../src/application/createCadApplication.js";

const fixture = resolve("tests/fixtures/dwg/export_sample.dwg");

async function sha256(path: string) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

test("opens and indexes a real DWG without modifying the source", async () => {
  const application = await createCadApplication();
  const runtime = createCadToolRuntime(application.capabilities);
  const before = await sha256(fixture);

  const opened = await runtime.call("cad.open_drawing", { path: fixture });
  const built = await runtime.call("cad.build_index", {
    drawingId: opened.drawingId
  });
  const index = await buildCadIndexForPath(fixture);

  assert.equal(opened.source.kind, "dwg");
  assert.equal(built.summary.entityCount, index.summary.entityCount);
  if (index.schemaVersion !== "cad-index/v0.2") {
    assert.fail(`Expected cad-index/v0.2, received ${index.schemaVersion}`);
  }
  assert.ok(index.entities.some(
    (entity) => entity.geometry.kind === "arc"
  ));
  const paper = index.entities.filter(
    (entity) => entity.space === "paper"
  );
  assert.equal(paper.length, index.summary.paperSpaceCount);
  assert.ok(paper.every((entity) => entity.layout !== "Model"));
  assert.ok(paper.some((entity) => entity.type === "VIEWPORT"));
  assert.equal(await sha256(fixture), before);
});

test("rejects unsupported drawing formats before reading them", async () => {
  const application = await createCadApplication();
  const runtime = createCadToolRuntime(application.capabilities);
  await assert.rejects(
    runtime.call("cad.open_drawing", { path: "missing.pdf" }),
    /Unsupported drawing format: \.pdf/
  );
});

test("rejects CAD files outside the configured workspace", async () => {
  const application = await createCadApplication({
    workspaceRoot: resolve("tests/fixtures/dxf")
  });
  const runtime = createCadToolRuntime(application.capabilities);

  await assert.rejects(
    runtime.call("cad.open_drawing", { path: fixture }),
    /Drawing path is outside workspace/
  );
});

test("rejects regular expressions with executable grouping", async () => {
  const application = await createCadApplication();
  const runtime = createCadToolRuntime(application.capabilities);
  const opened = await runtime.call("cad.open_drawing", {
    path: resolve("tests/fixtures/dxf/minimal-architectural.dxf")
  });

  await assert.rejects(
    runtime.call("cad.find_text", {
      drawingId: opened.drawingId,
      query: "(a+)+$",
      regex: true
    }),
    /Regex grouping is not supported/
  );
});

test("rejects text queries above the public search limit", async () => {
  const application = await createCadApplication();
  const runtime = createCadToolRuntime(application.capabilities);
  const opened = await runtime.call("cad.open_drawing", {
    path: resolve("tests/fixtures/dxf/minimal-architectural.dxf")
  });

  await assert.rejects(
    runtime.call("cad.find_text", {
      drawingId: opened.drawingId,
      query: "x".repeat(129)
    }),
    /query exceeds 128 characters/
  );
});
