import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import test from "node:test";

const repositoryRoot = resolve(import.meta.dirname, "../..");

test("Compose waits for healthy backend and DWG services before serving the product", () => {
  const result = spawnSync("docker", ["compose", "config", "--format", "json"], {
    cwd: repositoryRoot,
    encoding: "utf8",
    windowsHide: true,
  });
  assert.equal(result.status, 0, result.stderr);

  const config = JSON.parse(result.stdout);
  assert.ok(config.services.backend.healthcheck?.test?.length > 0);
  assert.ok(config.services.dwg.healthcheck?.test?.length > 0);
  assert.ok(config.services.frontend.healthcheck?.test?.length > 0);
  assert.equal(config.services.frontend.depends_on.backend.condition, "service_healthy");
  assert.equal(config.services.frontend.depends_on.dwg.condition, "service_healthy");
});
