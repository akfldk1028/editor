import assert from "node:assert/strict";
import { access } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";

const repositoryRoot = resolve(import.meta.dirname, "../..");

async function exists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

test("the product checkout exposes only canonical top-level module ownership", async () => {
  for (const path of [
    "frontend",
    "backend/app",
    "agents/planm",
    "infra/runtimes/gitagent",
    "infra/services/dwg",
    "infra/dev",
  ]) {
    assert.equal(await exists(resolve(repositoryRoot, path)), true, `${path} must exist`);
  }
  for (const path of ["agent", "agents/runtimes", "agents/dwg"]) {
    assert.equal(await exists(resolve(repositoryRoot, path)), false, `${path} must not exist`);
  }
});

test("frontend generated configuration artifacts do not pollute the source tree", async () => {
  for (const path of [
    "frontend/reserved_for_v2_dashboard",
    "frontend/vite.config.js",
    "frontend/vite.config.d.ts",
    "frontend/tsconfig.tsbuildinfo",
    "frontend/tsconfig.node.tsbuildinfo",
  ]) {
    assert.equal(await exists(resolve(repositoryRoot, path)), false, `${path} must not exist`);
  }
});
