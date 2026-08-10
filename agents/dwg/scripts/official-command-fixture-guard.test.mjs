import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const packageJson = JSON.parse(await readFile("package.json", "utf8"));
const scripts = packageJson.scripts;

function reachesFixtureGuard(scriptName, visited = new Set()) {
  if (visited.has(scriptName)) return false;
  visited.add(scriptName);

  const command = scripts[scriptName] ?? "";
  if (
    command.includes("scripts/**/*.test.mjs") ||
    command.includes("scripts/verify-fixture-hashes.test.mjs")
  ) {
    return true;
  }

  const dependencies = [
    ...command.matchAll(/\bnpm\s+test\b/g)
  ].map(() => "test");
  dependencies.push(
    ...[...command.matchAll(/\bnpm\s+run\s+([^\s&]+)/g)].map(
      (match) => match[1]
    )
  );

  return dependencies.some((dependency) =>
    reachesFixtureGuard(dependency, new Set(visited))
  );
}

test("official handoff commands cannot bypass fixture hash verification", () => {
  for (const command of ["test", "verify", "verify:all"]) {
    assert.equal(
      reachesFixtureGuard(command),
      true,
      `npm run ${command} must reach the fixture hash test`
    );
  }
});

test("foundation verification does not execute the fixture guard twice", () => {
  assert.equal(
    scripts["verify:foundation"].includes("npm run test:fixtures"),
    false
  );
  assert.equal(reachesFixtureGuard("verify:foundation"), true);
});
