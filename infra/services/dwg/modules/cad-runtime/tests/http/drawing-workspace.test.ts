import assert from "node:assert/strict";
import {
  mkdtemp,
  mkdir,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import { createDrawingWorkspace } from "../../src/http/drawingWorkspace.js";

const unusedRuntime = {
  async execute(): Promise<never> {
    throw new Error("not used");
  }
};

test("drawing workspace rejects configured paths outside its root", () => {
  const workspaceRoot = process.cwd();

  assert.throws(
    () => createDrawingWorkspace(workspaceRoot, "../outside.dwg", unusedRuntime),
    /outside workspace/i
  );
});

test("drawing workspace shares one indexed result across concurrent readers", async () => {
  const workspaceRoot = process.cwd();
  const drawingWorkspace = createDrawingWorkspace(
    workspaceRoot,
    "tests/fixtures/dwg/export_sample.dwg",
    unusedRuntime
  );

  const indexes = await Promise.all(
    Array.from({ length: 5 }, () => drawingWorkspace.getIndex())
  );

  assert.equal(indexes.every((index) => index === indexes[0]), true);
});

test("a pre-cancelled inspection never executes a CAD capability", async () => {
  let calls = 0;
  const drawingWorkspace = createDrawingWorkspace(
    process.cwd(),
    "tests/fixtures/dwg/export_sample.dwg",
    {
      async execute() {
        calls += 1;
        throw new Error("must not execute");
      }
    }
  );
  const controller = new AbortController();
  controller.abort(new Error("inspection cancelled"));

  await assert.rejects(
    drawingWorkspace.inspect([{ kind: "layer", value: "0" }], controller.signal),
    /cancelled/i
  );
  assert.equal(calls, 0);
});

test("drawing workspace rejects junctions that escape its canonical root", async (context) => {
  const container = await mkdtemp(resolve(tmpdir(), "dwg-workspace-"));
  context.after(() => rm(container, { recursive: true, force: true }));
  const workspaceRoot = resolve(container, "workspace");
  const outsideRoot = resolve(container, "outside");
  await mkdir(workspaceRoot);
  await mkdir(outsideRoot);
  await writeFile(resolve(outsideRoot, "secret.dwg"), "not a real drawing");
  await symlink(outsideRoot, resolve(workspaceRoot, "linked"), "junction");

  assert.throws(
    () => createDrawingWorkspace(workspaceRoot, "linked/secret.dwg", unusedRuntime),
    /outside workspace/i
  );
});
