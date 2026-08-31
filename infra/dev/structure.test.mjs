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
    "products/plan/frontend",
    "products/plan/backend/app",
    "products/plan/agents/planm",
    "platform/agent-runtimes/gitagent",
    "products/dwg",
    "infra/dev",
  ]) {
    assert.equal(await exists(resolve(repositoryRoot, path)), true, `${path} must exist`);
  }
  assert.equal(await exists(resolve(repositoryRoot, "agent")), false, "legacy agent/ must not exist");
});

test("frontend generated configuration artifacts do not pollute the source tree", async () => {
  for (const path of [
    "products/plan/frontend/reserved_for_v2_dashboard",
    "products/plan/frontend/vite.config.js",
    "products/plan/frontend/vite.config.d.ts",
    "products/plan/frontend/tsconfig.tsbuildinfo",
    "products/plan/frontend/tsconfig.node.tsbuildinfo",
  ]) {
    assert.equal(await exists(resolve(repositoryRoot, path)), false, `${path} must not exist`);
  }
});
