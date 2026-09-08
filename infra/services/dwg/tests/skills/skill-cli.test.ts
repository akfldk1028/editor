import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";

test("documented inspect CLI command runs from the repository root with one safe success summary", async () => {
  const result = await invokeDocumentedInspectCommand();
  assert.equal(result.code, 0, result.stderr);
  const summaries = result.stdout
    .split(/\r?\n/)
    .filter((line) => line.startsWith("{") && line.endsWith("}"));
  assert.equal(summaries.length, 1);
  const summary = JSON.parse(summaries[0]!);
  assert.deepEqual(Object.keys(summary).sort(), ["changeCount", "hasPreview", "skillId", "status", "warningCount"]);
  assert.deepEqual(summary, { skillId: "inspect-drawing", status: "passed", changeCount: 0, warningCount: 0, hasPreview: false });
  assert.doesNotMatch(result.stdout, /minimal-architectural|matches|[A-Za-z]:[\\/]/i);
});

test("skill CLI uses a distinct usage exit code and does not print raw failures", async () => {
  const result = await invoke("--unknown");
  assert.equal(result.code, 2);
  assert.equal(result.stdout.trim().split(/\r?\n/).length, 1);
  assert.deepEqual(JSON.parse(result.stdout), { skillId: "unknown", status: "failed", changeCount: 0, warningCount: 1, hasPreview: false });
  assert.doesNotMatch(result.stderr, /secret|snapshot|path/i);
});

test("skill CLI returns a bounded failure for an explicit document mismatch", async (context) => {
  const directory = await mkdtemp(resolve(tmpdir(), "skill-cli-mismatch-"));
  context.after(() => rm(directory, { recursive: true, force: true }));
  const input = resolve(directory, "input.json");
  await writeFile(input, JSON.stringify({ path: "tests/fixtures/dxf/minimal-architectural.dxf", layer: "A-WALL" }));

  const result = await invoke("--skill", "inspect-drawing", "--input", input, "--document-id", "drawing-other");
  assert.equal(result.code, 1);
  assert.deepEqual(JSON.parse(result.stdout), { skillId: "inspect-drawing", status: "failed", changeCount: 0, warningCount: 1, hasPreview: false });
  assert.equal(result.stdout.trim().split(/\r?\n/).length, 1);
});

test("CLI opens both comparison drawings and returns one bounded successful summary", async (context) => {
  const directory = await mkdtemp(resolve(tmpdir(), "skill-cli-compare-"));
  context.after(() => rm(directory, { recursive: true, force: true }));
  const input = resolve(directory, "input.json");
  await writeFile(input, "{}");

  const result = await invoke(
    "--skill", "compare-drawings",
    "--input", input,
    "--before", "tests/fixtures/dxf/minimal-architectural.dxf",
    "--after", "tests/fixtures/dwg/export_sample.dwg"
  );
  assert.equal(result.code, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    skillId: "compare-drawings",
    status: "passed",
    changeCount: 0,
    warningCount: 0,
    hasPreview: false
  });
  assert.equal(result.stdout.trim().split(/\r?\n/).length, 1);
  assert.doesNotMatch(result.stdout, /minimal-architectural|export_sample|drawingId|[A-Za-z]:[\\/]/i);
});

test("CLI rejects one-sided and duplicate comparison preload flags", async (context) => {
  const directory = await mkdtemp(resolve(tmpdir(), "skill-cli-compare-flags-"));
  context.after(() => rm(directory, { recursive: true, force: true }));
  const input = resolve(directory, "input.json");
  await writeFile(input, "{}");

  for (const args of [
    ["--before", "tests/fixtures/dxf/minimal-architectural.dxf"],
    [
      "--before", "tests/fixtures/dxf/minimal-architectural.dxf",
      "--before", "tests/fixtures/dwg/export_sample.dwg",
      "--after", "tests/fixtures/dwg/export_sample.dwg"
    ]
  ]) {
    const result = await invoke(
      "--skill", "compare-drawings",
      "--input", input,
      ...args
    );
    assert.equal(result.code, 2);
    assert.deepEqual(JSON.parse(result.stdout), {
      skillId: "unknown",
      status: "failed",
      changeCount: 0,
      warningCount: 1,
      hasPreview: false
    });
    assert.doesNotMatch(result.stdout + result.stderr, /minimal-architectural|export_sample|[A-Za-z]:[\\/]/i);
  }
});

test("CLI rejects an oversized comparison preload path as a bounded usage error", async (context) => {
  const directory = await mkdtemp(resolve(tmpdir(), "skill-cli-compare-bounds-"));
  context.after(() => rm(directory, { recursive: true, force: true }));
  const input = resolve(directory, "input.json");
  await writeFile(input, "{}");
  const oversizedPath = "x".repeat(4_097);

  const result = await invoke(
    "--skill", "compare-drawings",
    "--input", input,
    "--before", oversizedPath,
    "--after", "tests/fixtures/dwg/export_sample.dwg"
  );
  assert.equal(result.code, 2);
  assert.deepEqual(JSON.parse(result.stdout), {
    skillId: "unknown",
    status: "failed",
    changeCount: 0,
    warningCount: 1,
    hasPreview: false
  });
  assert.doesNotMatch(result.stdout + result.stderr, /x{64}/);
});

test("CLI rejects comparison preload flags for another skill or mixed caller IDs", async (context) => {
  const directory = await mkdtemp(resolve(tmpdir(), "skill-cli-compare-ambiguous-"));
  context.after(() => rm(directory, { recursive: true, force: true }));
  const input = resolve(directory, "input.json");
  await writeFile(input, "{}");
  const preload = [
    "--before", "tests/fixtures/dxf/minimal-architectural.dxf",
    "--after", "tests/fixtures/dwg/export_sample.dwg"
  ];

  for (const args of [
    ["--skill", "inspect-drawing", "--input", input, ...preload],
    [
      "--skill", "compare-drawings",
      "--input", input,
      ...preload,
      "--document-id", "caller-before"
    ]
  ]) {
    const result = await invoke(...args);
    assert.equal(result.code, 2);
    assert.deepEqual(JSON.parse(result.stdout), {
      skillId: "unknown",
      status: "failed",
      changeCount: 0,
      warningCount: 1,
      hasPreview: false
    });
    assert.doesNotMatch(result.stdout + result.stderr, /minimal-architectural|export_sample|caller-before|[A-Za-z]:[\\/]/i);
  }
});

function invoke(...args: string[]): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return invokeProcess(
    process.execPath,
    ["--import", "tsx", "modules/cad-runtime/harness/run-skill.ts", ...args]
  );
}

function invokeDocumentedInspectCommand(): Promise<{ code: number | null; stdout: string; stderr: string }> {
  const args = [
    "run", "skill", "--",
    "--skill", "inspect-drawing",
    "--input", "skills/inspect-drawing/examples/input.json"
  ];
  if (process.platform !== "win32") return invokeProcess("npm", args);
  return invokeProcess(
    process.env.ComSpec ?? "cmd.exe",
    [
      "/d",
      "/s",
      "/c",
      "npm run skill -- --skill inspect-drawing --input skills/inspect-drawing/examples/input.json"
    ]
  );
}

function invokeProcess(
  command: string,
  args: string[]
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      cwd: process.cwd(),
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk) => { stdout += chunk; });
    child.stderr.setEncoding("utf8").on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => resolvePromise({ code, stdout, stderr }));
  });
}
