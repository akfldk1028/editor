import { resolve } from "node:path";
import { createHash } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { canManageService } from './lifecycle.mjs';

const registry = JSON.parse(readFileSync(new URL('../config/services.json', import.meta.url), 'utf8'));

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
  const ownerRoot = resolve(process.env.ORCHESTRATOR_AGENT_DIR || resolve(repositoryRoot, '../agents/OrchestratorAgent'));
  const ownerState = resolve(ownerRoot, 'runtime/orchestrator/design.sqlite');
  const ownerConfigId = createHash('sha256').update(platform === 'win32' ? ownerState.toLowerCase() : ownerState).digest('hex');
  const definitions = {
    arr: {
      name: 'arr-domain',
      healthUrl: `${(process.env.EDITOR_ARR_URL || 'http://127.0.0.1:18320').replace(/\/$/, '')}/law/health/`,
      timeoutMs: 5_000,
      validate: ({ body }) => body?.status === 'ok' && body?.django === true,
      describe: ({ body }) => body?.ready === true
        ? 'Django reachable; law dependency ready; other domain operations not verified'
        : 'Django reachable; law dependency unavailable; other domain operations not verified',
    },
    orchestrator: {
      name: 'orchestrator-editor-api',
      healthUrl: 'http://127.0.0.1:8791/editor/v1/health',
      timeoutMs: 30_000,
      configId: ownerConfigId,
      validate: ({body}) => body?.service === 'orchestrator-editor-api' && body?.mode === 'local-execution' && body?.config_id === ownerConfigId,
    },
    backend: {
      name: "backend",
      command: "python",
      args: ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"],
      cwd: resolve(repositoryRoot),
      env: {
        EDITOR_ORCHESTRATOR_URL: 'http://127.0.0.1:8791',
        EDITOR_LAND_DATA_DIR: process.env.EDITOR_LAND_DATA_DIR || resolve(repositoryRoot, 'runtime/editor/land'),
        EDITOR_DESIGN_DATA_DIR: process.env.EDITOR_DESIGN_DATA_DIR || resolve(repositoryRoot, 'runtime/editor/design'),
        EDITOR_PUBLIC_URL: `http://127.0.0.1:${FRONTEND_PORT}`,
        EDITOR_SCENE_URL: `http://127.0.0.1:${EDITOR_PORT}${EDITOR_BASE_PATH}`,
        EDITOR_PLATFORM_DATA_DIR: process.env.EDITOR_PLATFORM_DATA_DIR || resolve(repositoryRoot, '../runtime/editor-platform'),
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
      // NEXT_PUBLIC_ is inlined at build time so packages that know nothing
      // about the host app can still resolve their own public assets.
      env: {
        PASCAL_BASE_PATH: EDITOR_BASE_PATH,
        NEXT_PUBLIC_BASE_PATH: EDITOR_BASE_PATH,
      },
      healthUrl: `http://127.0.0.1:${EDITOR_PORT}${EDITOR_BASE_PATH}/api/health`,
      publicUrl: `http://127.0.0.1:${FRONTEND_PORT}${EDITOR_BASE_PATH}`,
      timeoutMs: 180_000,
      validate: ({ body }) => body?.status === "ok" && body?.app === "editor",
    },
  };
  return Object.fromEntries(Object.entries(definitions).map(([key, service]) => {
    if (!registry[key]) throw new Error(`Missing lifecycle registration: ${key}`);
    return [key, { ...service, ...registry[key] }];
  }));
}

export function createNativeServiceDefinitions(repositoryRoot, platform = process.platform) {
  const { editor, backend, orchestrator, pascalMcp } = createServiceDefinitions(repositoryRoot, platform);
  const publicUrl = `http://127.0.0.1:${EDITOR_PORT}`;
  const localPython = resolve(repositoryRoot, '.venv', platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  return {
    orchestrator, pascalMcp,
    editor: { ...editor, publicUrl, healthUrl: `${publicUrl}/api/health`,
      env: { ...editor.env, PORT: String(EDITOR_PORT), PASCAL_BASE_PATH: '', NEXT_PUBLIC_BASE_PATH: '', EDITOR_BACKEND_URL: 'http://127.0.0.1:8000' } },
    backend: { ...backend, command: process.env.EDITOR_PYTHON || (existsSync(localPython) ? localPython : backend.command),
      env: { ...backend.env, EDITOR_PUBLIC_URL: publicUrl, EDITOR_SCENE_URL: publicUrl, PASCAL_EDITOR_URL: publicUrl },
      healthUrl: 'http://127.0.0.1:8000/api/v1/platform/health',
      validate: ({ body }) => body?.service === 'editor-platform' && body?.public_origin === publicUrl &&
        body?.scene_url === publicUrl && body?.storage_configured === true && body?.owner_configured === true,
      describe: () => 'Editor bindings configured; provider and project execution readiness require separate checks',
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
      return { state: "healthy", ...(service.describe ? { detail: service.describe({ response, body }) } : {}) };
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
    if (processInfo.created === true && canManageService(processInfo)) await killProcess(processInfo);
  }
}

function isOfflineError(error) {
  if (error instanceof TypeError) return true;
  const code = error?.cause?.code ?? error?.code;
  return code === "ECONNREFUSED" || code === "ECONNRESET" || code === "ETIMEDOUT";
}
