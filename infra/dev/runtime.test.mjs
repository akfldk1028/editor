import assert from "node:assert/strict";
import { resolve } from "node:path";
import test from "node:test";

import {
  createServiceDefinitions,
  probeService,
  stopOwnedProcesses,
  waitForService,
} from "./runtime.mjs";

const repositoryRoot = resolve(import.meta.dirname, "../..");

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function refused() {
  const error = new TypeError("fetch failed");
  error.cause = { code: "ECONNREFUSED" };
  return Promise.reject(error);
}

test("service definitions keep one product URL and explicit module working directories", () => {
  const services = createServiceDefinitions(repositoryRoot, "win32");

  assert.equal(services.frontend.publicUrl, "http://127.0.0.1:5173");
  assert.equal(services.backend.cwd, resolve(repositoryRoot));
  assert.equal(services.dwg.cwd, resolve(repositoryRoot, "infra/services/dwg"));
  assert.equal(services.frontend.cwd, resolve(repositoryRoot, "frontend"));
  assert.deepEqual(
    services.frontend.args.slice(-4),
    ["--host", "127.0.0.1", "--port", "5173"],
  );
  assert.ok(services.frontend.args.includes(resolve(repositoryRoot, "frontend/vite.config.ts")));
});

test("probeService accepts only the expected backend contract", async () => {
  const service = createServiceDefinitions(repositoryRoot, "win32").backend;

  const healthy = await probeService(service, async () =>
    jsonResponse(200, { info: { title: "PLANM API", version: "1.0.0" } }),
  );
  const occupied = await probeService(service, async () =>
    jsonResponse(200, { info: { title: "Another API" } }),
  );

  assert.equal(healthy.state, "healthy");
  assert.equal(occupied.state, "occupied");
});

test("probeService distinguishes an offline port from an incompatible service", async () => {
  const service = createServiceDefinitions(repositoryRoot, "win32").dwg;

  const offline = await probeService(service, refused);
  const occupied = await probeService(service, async () =>
    new Response("not json", { status: 404, headers: { "content-type": "text/plain" } }),
  );

  assert.equal(offline.state, "offline");
  assert.equal(occupied.state, "occupied");
});

test("waitForService retries offline probes until the contract is healthy", async () => {
  const service = createServiceDefinitions(repositoryRoot, "win32").dwg;
  let attempts = 0;
  const fetchImpl = async () => {
    attempts += 1;
    if (attempts === 1) return refused();
    return jsonResponse(200, { ok: true, service: "dwg-provider-gateway" });
  };

  const result = await waitForService(service, {
    fetchImpl,
    timeoutMs: 100,
    intervalMs: 1,
    sleep: async () => {},
  });

  assert.equal(result.state, "healthy");
  assert.equal(attempts, 2);
});

test("stopOwnedProcesses never receives reused services", async () => {
  const killed = [];
  await stopOwnedProcesses(
    [{ name: "backend", pid: 101 }, { name: "frontend", pid: 202 }],
    async (process) => killed.push(process),
  );

  assert.deepEqual(killed, [
    { name: "frontend", pid: 202 },
    { name: "backend", pid: 101 },
  ]);
});
