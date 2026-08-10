import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { chdir, cwd } from "node:process";
import { tmpdir } from "node:os";
import test from "node:test";

import {
  createRepositoryPaths,
  createRuntimePaths,
  findRepositoryRoot
} from "../../src/platform/repositoryPaths.js";
import { resolveWorkspaceCadPath } from "../../src/application/drawing-access/workspacePath.js";

test("repository paths do not depend on process.cwd", () => {
  const original = cwd();
  try {
    chdir(process.env.TEMP ?? "C:\\Windows\\Temp");
    const root = findRepositoryRoot(import.meta.url);
    const paths = createRepositoryPaths(root);
    assert.match(paths.parserProject, /modules[\\/]dwg-parser[\\/]src/);
    assert.match(paths.defaultDrawing, /tests[\\/]fixtures[\\/]dwg/);
  } finally {
    chdir(original);
  }
});

test("custom workspaces resolve the default fixture under the selected root", () => {
  const repositoryPaths = createRepositoryPaths(findRepositoryRoot(import.meta.url));
  const workspace = mkdtempSync(join(tmpdir(), "click-around-workspace-"));
  const drawing = join(workspace, "tests/fixtures/dwg/export_sample.dwg");
  mkdirSync(join(workspace, "tests/fixtures/dwg"), { recursive: true });
  writeFileSync(drawing, "fixture");

  try {
    const runtimePaths = createRuntimePaths(repositoryPaths, workspace);

    assert.equal(runtimePaths.workspace, resolve(workspace));
    assert.equal(
      runtimePaths.drawingPath,
      join("tests", "fixtures", "dwg", "export_sample.dwg")
    );
    assert.equal(
      resolveWorkspaceCadPath(runtimePaths.workspace, runtimePaths.drawingPath),
      drawing
    );
    assert.equal(
      createRuntimePaths(repositoryPaths, workspace, "custom.dwg").drawingPath,
      "custom.dwg"
    );
  } finally {
    rmSync(workspace, { recursive: true, force: true });
  }
});
