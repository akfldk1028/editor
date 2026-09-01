import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdtemp,
  mkdir,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join, relative, resolve } from "node:path";
import test from "node:test";

import {
  assertFileHash,
  loadFixtureManifest,
  summarizeIndex,
  type FixtureDescriptor
} from "@dwg/test-kit";
import type { CadEntityIndex } from "@dwg/contracts";

const repositoryRoot = resolve(import.meta.dirname, "../../..");

test("loads the checked-in DWG and DXF fixtures with their retained hashes", async () => {
  const fixtures = await loadFixtureManifest(repositoryRoot);

  assert.deepEqual(fixtures, [
    {
      id: "dwg.export-sample",
      path: "tests/fixtures/dwg/export_sample.dwg",
      sha256: "b60b4a7242e43b34ca35561b105b2dda30f2e373602ab5a12900ebc25b1e499b",
      kind: "dwg"
    },
    {
      id: "dxf.minimal-architectural",
      path: "tests/fixtures/dxf/minimal-architectural.dxf",
      sha256: "86be7bbdf2ca52e4343f0914e2986229229a2db90db9350453f7fc21c17b97b6",
      kind: "dxf"
    }
  ] satisfies FixtureDescriptor[]);

  for (const fixture of fixtures) {
    const fixturePath = resolve(repositoryRoot, fixture.path);
    const fixtureRelativePath = relative(
      resolve(repositoryRoot, "tests/fixtures"),
      fixturePath
    );

    assert.equal(isAbsolute(fixture.path), false);
    assert.equal(fixtureRelativePath.startsWith(".."), false);
    await assert.doesNotReject(() => assertFileHash(fixturePath, fixture.sha256));
  }
});

test("rejects fixture manifest paths that are absolute or escape tests/fixtures", async () => {
  await withFixtureRepository(async ({ repositoryRoot, outsidePath }) => {
    for (const path of [
      "C:\\outside\\drawing.dwg",
      "tests/fixtures/../../outside.dwg",
      outsidePath
    ]) {
      await writeManifest(repositoryRoot, [descriptor(path)]);
      await assert.rejects(
        () => loadFixtureManifest(repositoryRoot),
        /fixture path/i
      );
    }
  });
});

test("rejects a fixture symlink whose real path escapes tests/fixtures", async () => {
  await withFixtureRepository(async ({ fixtureRoot, outsidePath, repositoryRoot }) => {
    await symlink(outsidePath, join(fixtureRoot, "escaped.dwg"), "file");
    await writeManifest(repositoryRoot, [
      descriptor("tests/fixtures/escaped.dwg")
    ]);

    await assert.rejects(
      () => loadFixtureManifest(repositoryRoot),
      /fixture path/i
    );
  });
});

test("summarizes index invariants from index data with sorted stable handles", () => {
  const index: CadEntityIndex = {
    drawingId: "fixture-drawing",
    schemaVersion: "cad-index/v0.1",
    source: { kind: "dxf", displayName: "fixture.dxf", parser: "test" },
    summary: {
      entityCount: 999,
      layerCount: 999,
      unsupportedCount: 999,
      modelSpaceCount: 0,
      paperSpaceCount: 0
    },
    layers: [
      { name: "Walls", entityCount: 2, visible: true, frozen: false },
      { name: "Notes", entityCount: 1, visible: true, frozen: false }
    ],
    unsupported: [
      { type: "HATCH", count: 2, reason: "unsupported" },
      { type: "SPLINE", count: 1, reason: "unsupported" }
    ],
    entities: [
      entity("z-20"),
      entity(null),
      entity("A-10")
    ]
  };

  assert.deepEqual(summarizeIndex(index), {
    schemaVersion: "cad-index/v0.1",
    entityCount: 3,
    layerCount: 2,
    unsupportedCount: 3,
    handles: ["A-10", "z-20"]
  });
});

function entity(handle: string | null): CadEntityIndex["entities"][number] {
  return {
    id: `entity-${handle ?? "none"}`,
    handle,
    type: "LINE",
    layer: "Walls",
    space: "model",
    layout: "Model",
    bbox: null,
    text: null,
    blockName: null,
    attributes: {},
    warnings: [],
    geometry: {}
  };
}

function descriptor(path: string): { id: string; path: string; bytes: number; sha256: string } {
  return {
    id: "adversarial-fixture",
    path,
    bytes: 7,
    sha256: createHash("sha256").update("outside").digest("hex")
  };
}

async function withFixtureRepository(
  run: (paths: {
    repositoryRoot: string;
    fixtureRoot: string;
    outsidePath: string;
  }) => Promise<void>
): Promise<void> {
  const temporaryRoot = await mkdtemp(join(tmpdir(), "dwg-test-kit-"));
  const fixtureRoot = join(temporaryRoot, "tests", "fixtures");
  const outsidePath = join(temporaryRoot, "outside.dwg");

  try {
    await mkdir(fixtureRoot, { recursive: true });
    await writeFile(outsidePath, "outside");
    await run({ repositoryRoot: temporaryRoot, fixtureRoot, outsidePath });
  } finally {
    await rm(temporaryRoot, { recursive: true, force: true });
  }
}

async function writeManifest(
  repositoryRoot: string,
  fixtures: Array<{ id: string; path: string; bytes: number; sha256: string }>
): Promise<void> {
  await writeFile(
    join(repositoryRoot, "tests", "fixtures", "manifest.json"),
    JSON.stringify({ version: 1, fixtures })
  );
}
