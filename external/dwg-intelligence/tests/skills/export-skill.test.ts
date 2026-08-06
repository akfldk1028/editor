import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolve } from "node:path";
import test from "node:test";

import { parseCadSkillManifest } from "@dwg/skill-contracts";
import { createCadApplication } from "../../modules/cad-runtime/src/application/createCadApplication.js";
import {
  discoverCadSkills,
  loadCadSkillWorkflow,
  runCadSkillWorkflow
} from "../../modules/skill-runtime/src/index.js";

test("export-drawing declares exact write-copy and export permissions", async () => {
  const root = resolve("skills/export-drawing");
  const manifest = parseCadSkillManifest(
    JSON.parse(await readFile(resolve(root, "manifest.json"), "utf8"))
  );
  assert.deepEqual(manifest.permissions, ["write-copy", "export"]);
  const workflow = JSON.parse(
    await readFile(resolve(root, "workflows/default.json"), "utf8")
  ) as { steps: Array<{ capability: string }> };
  assert.deepEqual(workflow.steps.map((step) => step.capability), ["export.drawing"]);
});

test("export-report binds only host document state and declares export permission", async () => {
  const root = resolve("skills/export-report");
  const manifest = parseCadSkillManifest(
    JSON.parse(await readFile(resolve(root, "manifest.json"), "utf8"))
  );
  assert.deepEqual(manifest.permissions, ["export"]);
  assert.deepEqual(manifest.capabilities, ["export.report"]);
  assert.deepEqual(manifest.inputSchema, {
    type: "object",
    required: ["format"],
    properties: {
      format: { enum: ["json", "csv", "pdf", "svg"] }
    },
    additionalProperties: false
  });
  const workflow = JSON.parse(
    await readFile(resolve(root, "workflows/default.json"), "utf8")
  ) as { steps: Array<{ capability: string; input: Record<string, unknown> }> };
  assert.deepEqual(workflow.steps, [{
    id: "report",
    capability: "export.report",
    input: {
      documentId: "$host.documentId",
      revision: "$host.revision",
      format: "$input.format"
    }
  }]);
  assert.doesNotMatch(JSON.stringify({ manifest, workflow }), /path|grant/iu);
});

test("CLI injects a real host grant and executes export-drawing without a grant or path in skill input", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "cad-export-skill-cli-"));
  t.after(() => rm(root, { force: true, recursive: true }));
  const inputPath = join(root, "input.json");
  await writeFile(inputPath, JSON.stringify({
    expectedRevision: 0,
    baseFilename: "cli-host-grant",
    format: "dxf",
    version: "AC1032"
  }));
  const child = spawn(process.execPath, [
    "--import",
    "tsx",
    "modules/cad-runtime/harness/run-skill.ts",
    "--skill",
    "export-drawing",
    "--input",
    inputPath,
    "--drawing",
    "tests/fixtures/dxf/minimal-architectural.dxf"
  ], {
    cwd: resolve("."),
    stdio: ["ignore", "pipe", "pipe"]
  });
  const exportRoot = resolve(`tests/visual/test-results/export-roots/cli-${child.pid}`);
  t.after(() => rm(exportRoot, { force: true, recursive: true }));
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
  child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
  const exitCode = await new Promise<number | null>((resolveExit, reject) => {
    child.once("error", reject);
    child.once("exit", resolveExit);
  });

  assert.equal(exitCode, 0, stderr);
  assert.deepEqual(JSON.parse(stdout.trim()), {
    skillId: "export-drawing",
    status: "passed",
    changeCount: 0,
    warningCount: 0,
    hasPreview: false
  });
  assert.equal(
    await readFile(resolve(exportRoot, "cli-host-grant.dxf")).then(() => true, () => false),
    true
  );
});

test("CLI executes export-report with host-only scope and retains accessible bounded content", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "cad-report-skill-cli-"));
  t.after(() => rm(root, { force: true, recursive: true }));
  const inputPath = join(root, "input.json");
  await writeFile(inputPath, JSON.stringify({ format: "json" }));
  const child = spawn(process.execPath, [
    "--import",
    "tsx",
    "modules/cad-runtime/harness/run-skill.ts",
    "--skill",
    "export-report",
    "--input",
    inputPath,
    "--drawing",
    "tests/fixtures/dxf/minimal-architectural.dxf"
  ], {
    cwd: resolve("."),
    stdio: ["ignore", "pipe", "pipe"]
  });
  const exportRoot = resolve(`tests/visual/test-results/export-roots/cli-${child.pid}`);
  t.after(() => rm(exportRoot, { force: true, recursive: true }));
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8").on("data", (chunk: string) => { stdout += chunk; });
  child.stderr.setEncoding("utf8").on("data", (chunk: string) => { stderr += chunk; });
  const exitCode = await new Promise<number | null>((resolveExit, reject) => {
    child.once("error", reject);
    child.once("exit", resolveExit);
  });

  assert.equal(exitCode, 0, stderr);
  const summary = JSON.parse(stdout.trim()) as {
    skillId: string;
    status: string;
    artifact: {
      filename: string;
      mediaType: string;
      sha256: string;
    };
  };
  assert.equal(summary.skillId, "export-report");
  assert.equal(summary.status, "passed");
  assert.deepEqual(Object.keys(summary.artifact).sort(), [
    "filename",
    "mediaType",
    "sha256"
  ]);
  assert.match(summary.artifact.mediaType, /^application\/json/u);
  assert.match(summary.artifact.sha256, /^[0-9A-F]{64}$/u);
  const report = JSON.parse(
    await readFile(resolve(exportRoot, summary.artifact.filename), "utf8")
  );
  assert.equal(report.document.documentId, "86be7bbdf2ca52e4");
  assert.doesNotMatch(stdout + stderr, /destinationGrantId|[A-Za-z]:[\\/]/u);
});

test("export-drawing denies missing write-copy permission and honors pre-execution cancellation", async (t) => {
  const exportRoot = await mkdtemp(join(tmpdir(), "cad-export-skill-policy-"));
  t.after(() => rm(exportRoot, { force: true, recursive: true }));
  const application = await createCadApplication({
    workspaceRoot: resolve("."),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    exportRoot
  });
  const grant = await application.requestDestinationGrant();
  assert.ok(grant);
  const skill = (await discoverCadSkills(resolve("skills"), "cad-capabilities/v1"))
    .find((candidate) => candidate.manifest.id === "export-drawing");
  assert.ok(skill);
  const workflow = await loadCadSkillWorkflow(skill);
  const common = {
    skill,
    workflow,
    documentId: application.currentIndex().drawingId,
    input: {
      expectedRevision: 0,
      baseFilename: "policy-check",
      format: "dxf",
      version: "AC1032"
    },
    hostInput: {
      documentId: application.currentIndex().drawingId,
      destinationGrantId: grant.grantId
    },
    capabilities: application.capabilities
  };

  const denied = await runCadSkillWorkflow({
    ...common,
    grantedPermissions: ["export"]
  });
  assert.equal(
    (denied.steps[0]?.output as { error: { code: string } }).error.code,
    "PERMISSION_DENIED"
  );

  const controller = new AbortController();
  controller.abort();
  const cancelled = await runCadSkillWorkflow({
    ...common,
    grantedPermissions: ["write-copy", "export"],
    signal: controller.signal
  });
  assert.equal(cancelled.status, "cancelled");
  assert.equal(
    (cancelled.steps[0]?.output as { error: { code: string } }).error.code,
    "CANCELLED"
  );
});
