import assert from "node:assert/strict";
import test from "node:test";

import { runProcess } from "../../src/providers/cli/processRunner.js";

test("aborting a provider request terminates the child process", async () => {
  const controller = new AbortController();
  const startedAt = Date.now();
  const running = runProcess({
    command: process.execPath,
    args: ["-e", "setInterval(() => {}, 1000)"],
    cwd: process.cwd(),
    env: process.env,
    signal: controller.signal,
    timeoutMs: 2_000
  });

  setTimeout(() => controller.abort(), 50);
  const result = await running;

  assert.equal(result.errorCode, "ABORT_ERR");
  assert.match(result.stderr, /cancel/i);
  assert.ok(Date.now() - startedAt < 1_000);
});

test("terminates a provider process whose output exceeds one MiB", async () => {
  const result = await runProcess({
    command: process.execPath,
    args: ["-e", "process.stdout.write('x'.repeat(1_100_000))"],
    cwd: process.cwd(),
    env: process.env,
    timeoutMs: 2_000
  });

  assert.equal(result.exitCode, null);
  assert.equal(result.errorCode, "EOUTPUTLIMIT");
  assert.ok(result.stdout.length <= 1_048_576);
  assert.match(result.stderr, /output limit/i);
});
