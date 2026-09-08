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
  assert.deepEqual(
    services.frontend.args.slice(-4),
    ["--host", "127.0.0.1", "--port", "5173"],
  );
  // The app runs from its own directory, so vite resolves its own config.
  assert.equal(services.frontend.cwd, resolve(repositoryRoot, "frontend/app/planm"));
});

test("the editor and the bridge that reaches it are part of the product", () => {
  const services = createServiceDefinitions(repositoryRoot, "win32");

  assert.equal(services.editor.cwd, resolve(repositoryRoot));
  assert.equal(services.pascalMcp.cwd, resolve(repositoryRoot));

  // One origin: the editor is reached through the shell, not on its own port.
  assert.equal(services.editor.publicUrl, "http://127.0.0.1:5173/editor");
  // Next must know it is mounted under that path, not just proxied to it.
  assert.equal(services.editor.env.PASCAL_BASE_PATH, "/editor");
  assert.ok(services.editor.healthUrl.startsWith("http://127.0.0.1:3002/editor/"));

  // The MCP server only answers /health once it knows which instance it is.
  assert.equal(services.pascalMcp.env.PASCAL_INSTANCE_ID, "plan-dev");

  // The backend publishes through the bridge, so it must be told where it is,
  // and the URL it hands back has to be one a browser can open.
  assert.equal(services.backend.env.PASCAL_MCP_URL, "http://127.0.0.1:3917/mcp");
  assert.equal(services.backend.env.PASCAL_EDITOR_URL, "http://127.0.0.1:5173/editor");
});

test("each service accepts only its own health contract", () => {
  const services = createServiceDefinitions(repositoryRoot, "win32");

  assert.ok(services.editor.validate({ body: { status: "ok", app: "editor" } }));
  assert.ok(!services.editor.validate({ body: { status: "ok", app: "mcp" } }));
  assert.ok(services.pascalMcp.validate({ body: { status: "ok", app: "mcp" } }));
  assert.ok(!services.pascalMcp.validate({ body: { status: "ok", app: "editor" } }));
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
