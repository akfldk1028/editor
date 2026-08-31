import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import test from "node:test";

const repositoryRoot = resolve(import.meta.dirname, "../..");

function composeConfig() {
  const result = spawnSync("docker", ["compose", "config", "--format", "json"], {
    cwd: repositoryRoot,
    encoding: "utf8",
    windowsHide: true,
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test("Compose waits for healthy backend and DWG services before serving the product", () => {
  const config = composeConfig();
  assert.ok(config.services.backend.healthcheck?.test?.length > 0);
  assert.ok(config.services.dwg.healthcheck?.test?.length > 0);
  assert.ok(config.services.frontend.healthcheck?.test?.length > 0);
  assert.equal(config.services.frontend.depends_on.backend.condition, "service_healthy");
  assert.equal(config.services.frontend.depends_on.dwg.condition, "service_healthy");
});

test("the DWG image never seeds a path that a mounted volume then hides", () => {
  const mountTargets = composeConfig()
    .services.dwg.volumes.map((volume) => volume.target)
    .filter(Boolean);
  assert.ok(mountTargets.length > 0, "the DWG service must mount its run and export volumes");

  const dockerfile = readFileSync(
    resolve(repositoryRoot, "products/dwg/infra/docker/Dockerfile"),
    "utf8",
  );
  const buildSteps = dockerfile
    .replace(/\\\r?\n/g, " ")
    .split(/\r?\n/)
    .filter((line) => line.startsWith("RUN "));

  for (const step of buildSteps) {
    for (const target of mountTargets) {
      assert.ok(
        !step.includes(target),
        `build step writes into the mounted ${target}; a non-empty volume would hide it: ${step}`,
      );
    }
  }
});
