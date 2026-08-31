import assert from "node:assert/strict";
import { resolve } from "node:path";
import test from "node:test";

import type { CadEntityIndexV02 } from "@dwg/contracts";

import { buildIndexFromDwgFile } from "../../src/parsers/dwg/acadSharpIndexer.js";

function indexFor(parserProject: string): CadEntityIndexV02 {
  return {
    schemaVersion: "cad-index/v0.2",
    drawingId: parserProject,
    source: {
      kind: "dwg",
      displayName: "shared.dwg",
      parser: parserProject
    },
    summary: {
      entityCount: 0,
      layerCount: 0,
      unsupportedCount: 0,
      modelSpaceCount: 0,
      paperSpaceCount: 0
    },
    layers: [],
    entities: [],
    unsupported: []
  };
}

test("same drawing uses separate pending and result cache entries per parser project", async () => {
  const drawing = resolve("tests/fixtures/cache-key-shared.dwg");
  const parserA = resolve("tests/fixtures/parser-a/parser.csproj");
  const parserB = resolve("tests/fixtures/parser-b/parser.csproj");
  const releases = new Map<string, () => void>();
  const runParser = async (_drawing: string, parserProject: string) => {
    await new Promise<void>((resolvePending) => {
      releases.set(parserProject, resolvePending);
    });
    return indexFor(parserProject);
  };

  const pendingA = buildIndexFromDwgFile(drawing, {
    parserProject: parserA,
    runParser
  });
  const pendingB = buildIndexFromDwgFile(drawing, {
    parserProject: parserB,
    runParser
  });

  assert.equal(releases.size, 2);
  releases.get(parserA)?.();
  releases.get(parserB)?.();

  const [resultA, resultB] = await Promise.all([pendingA, pendingB]);
  assert.equal(resultA.drawingId, parserA);
  assert.equal(resultB.drawingId, parserB);
  assert.notStrictEqual(resultA, resultB);

  assert.strictEqual(
    await buildIndexFromDwgFile(drawing, {
      parserProject: parserA,
      runParser
    }),
    resultA
  );
  assert.strictEqual(
    await buildIndexFromDwgFile(drawing, {
      parserProject: parserB,
      runParser
    }),
    resultB
  );
});
