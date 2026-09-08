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
    "frontend/app/planm/reserved_for_v2_dashboard",
    "frontend/app/planm/vite.config.js",
    "frontend/app/planm/vite.config.d.ts",
    "frontend/app/planm/tsconfig.tsbuildinfo",
    "frontend/app/planm/tsconfig.node.tsbuildinfo",
  ]) {
    assert.equal(await exists(resolve(repositoryRoot, path)), false, `${path} must not exist`);
  }
});
