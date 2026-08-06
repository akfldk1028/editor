import assert from "node:assert/strict";
import test from "node:test";

import { parseE2eArgs } from "./run-e2e.mjs";

test("defaults to the repository drawing and forwards no arguments", () => {
  assert.deepEqual(parseE2eArgs([]), {
    drawingPath: null,
    playwrightArgs: []
  });
});

test("reads a drawing from the separated flag form", () => {
  assert.deepEqual(parseE2eArgs(["--drawing", "tests/fixtures/dxf/minimal-architectural.dxf"]), {
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    playwrightArgs: []
  });
});

test("reads a drawing from the inline flag form", () => {
  assert.deepEqual(parseE2eArgs(["--drawing=tests/fixtures/dwg/export_sample.dwg"]), {
    drawingPath: "tests/fixtures/dwg/export_sample.dwg",
    playwrightArgs: []
  });
});

test("forwards every unrelated argument to Playwright in order", () => {
  assert.deepEqual(parseE2eArgs(["save-as", "--drawing=a.dxf", "--headed", "--workers=1"]), {
    drawingPath: "a.dxf",
    playwrightArgs: ["save-as", "--headed", "--workers=1"]
  });
});

test("rejects a drawing flag without a value", () => {
  assert.throws(() => parseE2eArgs(["--drawing"]), /--drawing requires a repository-relative path/u);
  assert.throws(() => parseE2eArgs(["--drawing="]), /--drawing requires a repository-relative path/u);
  assert.throws(() => parseE2eArgs(["--drawing", "--headed"]), /--drawing requires a repository-relative path/u);
});

test("rejects a drawing flag repeated with conflicting values", () => {
  assert.throws(
    () => parseE2eArgs(["--drawing=a.dxf", "--drawing=b.dwg"]),
    /--drawing was provided more than once/u
  );
});

test("rejects an absolute or escaping drawing path", () => {
  assert.throws(() => parseE2eArgs(["--drawing=/etc/passwd"]), /repository-relative/u);
  assert.throws(() => parseE2eArgs(["--drawing=C:\\\\drawings\\\\a.dwg"]), /repository-relative/u);
  assert.throws(() => parseE2eArgs(["--drawing=../outside.dwg"]), /repository-relative/u);
});
