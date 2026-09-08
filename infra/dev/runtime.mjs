import { resolve } from "node:path";

function npmCommand(platform) {
  return platform === "win32" ? "npm.cmd" : "npm";
}

/** Where the editor and the MCP bridge listen during development. */
export const EDITOR_PORT = 3002;
export const PASCAL_MCP_PORT = 3917;
export const FRONTEND_PORT = 5173;
/** The editor is one surface of the shell, reachable at this path. */
export const EDITOR_BASE_PATH = "/editor";

export function createServiceDefinitions(repositoryRoot, platform = process.platform) {
  const npm = npmCommand(platform);
  return {
    backend: {
      name: "backend",
      command: "python",
      args: ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"],
      cwd: resolve(repositoryRoot),
      env: {
        PASCAL_MCP_URL: `http://127.0.0.1:${PASCAL_MCP_PORT}/mcp`,
        PASCAL_EDITOR_URL: `http://127.0.0.1:${FRONTEND_PORT}${EDITOR_BASE_PATH}`,
      },
      healthUrl: "http://127.0.0.1:8000/openapi.json",
      timeoutMs: 30_000,
      validate: ({ body }) => body?.info?.title === "PLANM API",
    },
    dwg: {
      name: "dwg",
      command: npm,
      args: ["run", "gateway"],
      cwd: resolve(repositoryRoot, "infra/services/dwg"),
      healthUrl: "http://127.0.0.1:4317/api/health",
      timeoutMs: 120_000,
      validate: ({ body }) => body?.ok === true && body?.service === "dwg-provider-gateway",
    },
    frontend: {
      name: "frontend",
      command: npm,
      args: ["run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
      // Its own directory: vite picks up the config sitting next to it, and
      // `frontend/` itself holds no package.json now that the app moved into
      // frontend/app/planm.
      cwd: resolve(repositoryRoot, "frontend/app/planm"),
      healthUrl: "http://127.0.0.1:5173/api/drawing",
      publicUrl: "http://127.0.0.1:5173",
      timeoutMs: 30_000,
      validate: ({ body }) => body?.schemaVersion === "cad-index/v0.2",
    },
    // The Pascal side of the product. Kept as its own services rather than
    // folded into the PLAN frontend: they are separate applications with
    // separate toolchains, wired together by the bridge below.
    pascalMcp: {
      name: "pascal-mcp",
      command: "bun",
      args: [
        "run",
        "backend/mcp/src/bin/pascal-mcp.ts",
        "--http",
        "--port",
        String(PASCAL_MCP_PORT),
      ],
      cwd: resolve(repositoryRoot),
      // `/health` only answers when the server knows its instance, so name one.
      env: { PASCAL_INSTANCE_ID: "plan-dev" },
      healthUrl: `http://127.0.0.1:${PASCAL_MCP_PORT}/health`,
      timeoutMs: 60_000,
      validate: ({ body }) => body?.status === "ok" && body?.app === "mcp",
    },
    editor: {
      name: "editor",
      command: "bun",
      // Through turbo so the workspace packages it depends on are built first.
      args: ["run", "dev", "--filter", "editor"],
      cwd: resolve(repositoryRoot),
      // Served as one surface of the product shell, so Next must know it is
      // mounted under a path rather than at the root.
      env: { PASCAL_BASE_PATH: EDITOR_BASE_PATH },
      healthUrl: `http://127.0.0.1:${EDITOR_PORT}${EDITOR_BASE_PATH}/api/health`,
      publicUrl: `http://127.0.0.1:${FRONTEND_PORT}${EDITOR_BASE_PATH}`,
      timeoutMs: 180_000,
      validate: ({ body }) => body?.status === "ok" && body?.app === "editor",
    },
  };
}

export async function probeService(service, fetchImpl = fetch) {
  try {
    const response = await fetchImpl(service.healthUrl, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(5_000),
    });
    const contentType = response.headers.get("content-type") ?? "";
    let body = null;
    if (contentType.includes("application/json")) {
      try {
        body = await response.json();
      } catch {
        return { state: "occupied", detail: "invalid JSON response" };
      }
    }
    if (response.ok && service.validate({ response, body })) {
      return { state: "healthy" };
    }
    return { state: "occupied", detail: `HTTP ${response.status} or incompatible contract` };
  } catch (error) {
    if (isOfflineError(error)) return { state: "offline" };
    return { state: "offline", detail: error instanceof Error ? error.message : String(error) };
  }
}

export async function waitForService(service, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const timeoutMs = options.timeoutMs ?? service.timeoutMs;
  const intervalMs = options.intervalMs ?? 250;
  const sleep = options.sleep ?? ((milliseconds) => new Promise((resolveSleep) => setTimeout(resolveSleep, milliseconds)));
  const isExited = options.isExited ?? (() => false);
  const deadline = Date.now() + timeoutMs;
  let latest = { state: "offline" };

  while (Date.now() <= deadline) {
    if (isExited()) return { state: "failed", detail: "process exited before readiness" };
    latest = await probeService(service, fetchImpl);
    if (latest.state === "healthy" || latest.state === "occupied") return latest;
    await sleep(intervalMs);
  }
  return { state: "timeout", detail: latest.detail ?? `not ready after ${timeoutMs}ms` };
}

export async function stopOwnedProcesses(ownedProcesses, killProcess) {
  for (const processInfo of [...ownedProcesses].reverse()) {
    await killProcess(processInfo);
  }
}

function isOfflineError(error) {
  if (error instanceof TypeError) return true;
  const code = error?.cause?.code ?? error?.code;
  return code === "ECONNREFUSED" || code === "ECONNRESET" || code === "ETIMEDOUT";
}
