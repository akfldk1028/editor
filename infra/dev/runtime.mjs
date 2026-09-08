import { resolve } from "node:path";

function npmCommand(platform) {
  return platform === "win32" ? "npm.cmd" : "npm";
}

export function createServiceDefinitions(repositoryRoot, platform = process.platform) {
  const npm = npmCommand(platform);
  return {
    backend: {
      name: "backend",
      command: "python",
      args: ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"],
      cwd: resolve(repositoryRoot),
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
      args: [
        "run",
        "dev",
        "--",
        "--config",
        resolve(repositoryRoot, "frontend/app/planm/vite.config.ts"),
        "--host",
        "127.0.0.1",
        "--port",
        "5173",
      ],
      cwd: resolve(repositoryRoot, "frontend"),
      healthUrl: "http://127.0.0.1:5173/api/drawing",
      publicUrl: "http://127.0.0.1:5173",
      timeoutMs: 30_000,
      validate: ({ body }) => body?.schemaVersion === "cad-index/v0.2",
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
