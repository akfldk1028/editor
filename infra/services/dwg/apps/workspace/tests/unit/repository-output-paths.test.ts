import assert from "node:assert/strict";
import test from "node:test";
import { dirname, resolve } from "node:path";
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import {
  documentationCaptureDirectory,
  docsExportRoot,
  e2eExportRoot,
  e2eArtifactPath,
  oauthArtifactPath,
  resolveOwnedFile
} from "../support/repositoryOutputPaths.ts";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

test("workspace-generated visual outputs resolve from the repository root", () => {
  assert.equal(
    documentationCaptureDirectory,
    resolve(repositoryRoot, "docs/ui-captures")
  );
  assert.equal(
    oauthArtifactPath("codex"),
    resolve(
      repositoryRoot,
      "tests/visual/test-results/live-oauth/oauth-codex-persistent-browser-e2e.png"
    )
  );
  assert.equal(
    e2eArtifactPath("loaded-1440x900.png"),
    resolve(
      repositoryRoot,
      "tests/visual/test-results/e2e-artifacts/loaded-1440x900.png"
    )
  );
});

test("browser export roots are isolated process-owned children", () => {
  const root = resolve(repositoryRoot, "tests/visual/test-results/export-roots");
  assert.equal(e2eExportRoot, resolve(root, `e2e-${process.pid}`));
  assert.equal(docsExportRoot, resolve(root, `docs-${process.pid}`));
  assert.notEqual(e2eExportRoot, docsExportRoot);
});

test("owned output paths allow normal and nested filenames", () => {
  assert.equal(
    resolveOwnedFile("C:/owned-output", "capture.png"),
    resolve("C:/owned-output", "capture.png")
  );
  assert.equal(
    resolveOwnedFile("C:/owned-output", "nested/capture.png"),
    resolve("C:/owned-output", "nested/capture.png")
  );
});

test("owned output paths reject traversal and absolute filenames", () => {
  const root = "C:/owned-output";

  for (const fileName of [
    "../capture.png",
    "nested/../../capture.png",
    "C:\\outside\\capture.png",
    "/outside/capture.png"
  ]) {
    assert.throws(
      () => resolveOwnedFile(root, fileName),
      /owned output directory/i
    );
  }
});

test("actual E2E specs cannot write tracked documentation captures", async () => {
  const e2eDirectory = resolve(repositoryRoot, "apps/workspace/tests/e2e");
  const specFiles = (await readdir(e2eDirectory))
    .filter((fileName) => fileName.endsWith(".spec.ts"));
  for (const fileName of specFiles) {
    const source = await readFile(resolve(e2eDirectory, fileName), "utf8");
    assert.doesNotMatch(
      source,
      /\bdocumentationCapturePath\b/u,
      `${fileName} must use Playwright testInfo.outputPath for actual-run artifacts`
    );
  }
});
