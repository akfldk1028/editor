import { createWriteStream } from "node:fs";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  createServiceDefinitions,
  probeService,
  stopOwnedProcesses,
  waitForService,
} from "./runtime.mjs";

const repositoryRoot = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const logRoot = resolve(repositoryRoot, "logs/dev");
const services = createServiceDefinitions(repositoryRoot);
const ownedProcesses = [];
let shuttingDown = false;

await main();

async function main() {
  await mkdir(logRoot, { recursive: true });
  try {
    // Everything that does not depend on another service starts together.
    await Promise.all([
      ensureService(services.pascalMcp),
      ensureService(services.dwg),
      ensureService(services.editor),
    ]);
    // The backend reads PASCAL_MCP_URL when it publishes, so bring it up after.
    await ensureService(services.backend);
    await ensureService(services.frontend);
    const page = await fetch(services.frontend.publicUrl, { signal: AbortSignal.timeout(5_000) });
    if (!page.ok || !(await page.text()).includes("id=\"root\"")) {
      throw new Error("Frontend HTML contract failed after API readiness.");
    }
    console.log(`\nPLAN product ready: ${services.frontend.publicUrl}`);
    console.log("  DWG workspace and PLANM planning share that shell.");
    console.log(`Pascal editor:      ${services.editor.publicUrl}`);
    console.log("  An approved PLANM alternative publishes into it via");
    console.log("  POST /api/v1/planm/runs/{run_id}/pascal\n");
    if (ownedProcesses.length === 0) return;
    await waitForShutdown();
  } catch (error) {
    console.error(`\nProduct startup failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  } finally {
    await shutdown();
  }
}

async function ensureService(service) {
  const current = await probeService(service);
  if (current.state === "healthy") {
    console.log(`[reuse] ${service.name}: ${service.healthUrl}`);
    return;
  }
  if (current.state === "occupied") {
    throw new Error(`${service.name} port is occupied by an incompatible service (${current.detail}).`);
  }

  const child = startService(service);
  const readiness = await waitForService(service, {
    isExited: () => child.exitCode !== null,
  });
  if (readiness.state !== "healthy") {
    throw new Error(`${service.name} did not become ready (${readiness.detail ?? readiness.state}).`);
  }
  console.log(`[ready] ${service.name}: ${service.healthUrl}`);
}

function startService(service) {
  const log = createWriteStream(resolve(logRoot, `${service.name}.log`), { flags: "a" });
  log.write(`\n[${new Date().toISOString()}] ${service.command} ${service.args.join(" ")}\n`);
  const child = spawn(service.command, service.args, {
    cwd: service.cwd,
    env: { ...process.env, ...service.env },
    shell: process.platform === "win32",
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  ownedProcesses.push({ name: service.name, pid: child.pid, child, log });
  child.stdout.on("data", (chunk) => writeServiceOutput(service.name, chunk, log, false));
  child.stderr.on("data", (chunk) => writeServiceOutput(service.name, chunk, log, true));
  child.once("error", (error) => log.write(`[spawn-error] ${error.message}\n`));
  console.log(`[start] ${service.name}`);
  return child;
}

function writeServiceOutput(name, chunk, log, isError) {
  log.write(chunk);
  const target = isError ? process.stderr : process.stdout;
  target.write(`[${name}] ${chunk}`);
}

function waitForShutdown() {
  return new Promise((resolveShutdown, reject) => {
    const requestShutdown = () => {
      shuttingDown = true;
      resolveShutdown();
    };
    process.once("SIGINT", requestShutdown);
    process.once("SIGTERM", requestShutdown);
    for (const processInfo of ownedProcesses) {
      processInfo.child.once("exit", (code) => {
        if (!shuttingDown) reject(new Error(`${processInfo.name} exited unexpectedly with code ${code}.`));
      });
    }
  });
}

async function shutdown() {
  if (ownedProcesses.length === 0) return;
  shuttingDown = true;
  await stopOwnedProcesses(ownedProcesses, killProcessTree);
  for (const processInfo of ownedProcesses) processInfo.log.end();
}

async function killProcessTree(processInfo) {
  if (!processInfo.pid || processInfo.child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(processInfo.pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
    return;
  }
  processInfo.child.kill("SIGTERM");
}
