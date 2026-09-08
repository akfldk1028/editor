import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const liveSpecPath = "apps/workspace/tests/e2e/live-oauth-cli.spec.ts";
const smokePath = "modules/cad-runtime/harness/provider-smoke.ts";
const smokeHelperPath =
  "modules/cad-runtime/harness/provider-smoke-summary.ts";

test("live OAuth installs init redaction before navigation and avoids raw assertions", async () => {
  const source = await readFile(liveSpecPath, "utf8");
  const installIndex = source.indexOf("installLiveOAuthFailureSafety(page)");
  const navigationIndex = source.indexOf("page.goto(");

  assert.notEqual(installIndex, -1, "live OAuth init redaction is missing");
  assert.equal(
    installIndex < navigationIndex,
    true,
    "live OAuth init redaction must run before first navigation"
  );

  const bannedPatterns = [
    /expect\s*\(\s*sessionId\s*\)\s*\.toMatch/,
    /expect\s*\(\s*resumed\.sessionId\s*\)\s*\.toBe/,
    /expect\s*\(\s*consoleErrors\s*\)\s*\.toEqual/,
    /getByRole\s*\(\s*["']textbox["']/,
    /getByRole\s*\(\s*["']button["']/,
    /\.(?:fill|type)\s*\(\s*message\b/
  ];
  for (const pattern of bannedPatterns) {
    assert.equal(pattern.test(source), false, `banned live pattern: ${pattern}`);
  }
  assert.equal(
    source.includes("List one TEXT or MTEXT object"),
    false,
    "live spec must not embed the raw initial prompt near failure sites"
  );
  assert.equal(
    source.includes("Continue the same session"),
    false,
    "live spec must not embed the raw resume prompt near failure sites"
  );
});

test("provider smoke never passes raw response or session values to assertions", async () => {
  const source = [
    await readFile(smokePath, "utf8"),
    await readFile(smokeHelperPath, "utf8")
  ].join("\n");
  const bannedPatterns = [
    /assert\.match\s*\(\s*result\.text/,
    /assert\.match\s*\(\s*resumed\.text/,
    /assert\.equal\s*\(\s*resumed\.sessionId/,
    /assert\.(?:equal|match)\s*\(\s*result\.sessionId/,
    /expect\s*\(\s*(?:result|resumed)\.(?:text|sessionId)\s*\)/
  ];

  for (const pattern of bannedPatterns) {
    assert.equal(pattern.test(source), false, `banned smoke pattern: ${pattern}`);
  }
});
