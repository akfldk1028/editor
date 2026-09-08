import assert from "node:assert/strict";
import { mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createConfiguredSourceDocumentResolver } from "../../src/application/drawing-access/sourceDocumentResolver.js";

test("configured resolver accepts only its drawing and recomputes evidence", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "cad-source-resolver-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const source = join(root, "drawing.dwg");
  await writeFile(source, "first");
  let pass = 0;
  const resolver = createConfiguredSourceDocumentResolver({
    documentId: "dwg:configured",
    configuredPath: await realpath(source),
    readSha256: async () => `${pass++ === 0 ? "A" : "B"}`.repeat(64),
    readEvidence: async () => ({
      index: index(),
      sourceSha256: `${pass < 2 ? "A" : "B"}`.repeat(64),
      drawingVersion: "AC1032",
      units: "Millimeters"
    })
  });

  assert.equal((await resolver.resolve("dwg:configured")).sourceSha256, "A".repeat(64));
  await writeFile(source, "second");
  assert.equal((await resolver.resolve("dwg:configured")).sourceSha256, "B".repeat(64));
  await assert.rejects(() => resolver.resolve("dwg:other"), /CAD_SAVE_SOURCE_MISMATCH/);
});

function index() {
  return {
    schemaVersion: "cad-index/v0.2" as const,
    drawingId: "dwg:configured",
    source: { kind: "dwg" as const, displayName: "drawing.dwg", parser: "test" },
    drawing: { fileVersion: "AC1032", units: "Millimeters" },
    summary: { entityCount: 0, layerCount: 0, unsupportedCount: 0, modelSpaceCount: 0, paperSpaceCount: 0 },
    layers: [],
    entities: [],
    unsupported: []
  };
}
