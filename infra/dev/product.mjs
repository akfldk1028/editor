import { createWriteStream } from "node:fs";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  createServiceDefinitions,
  createNativeServiceDefinitions,
  probeService,
  stopOwnedProcesses,
  waitForService,
} from "./runtime.mjs";
import { canManageService, ensureService as ensureManagedService, settleStartup } from './lifecycle.mjs';
import { checkWorkspaceLinks } from './workspace-links.mjs';

const repositoryRoot = resolve(fileURLToPath(new URL("../..", import.meta.url)));
const logRoot = resolve(repositoryRoot, "logs/dev");
const native = process.argv.includes('--native-editor');
const services = native ? createNativeServiceDefinitions(repositoryRoot) : createServiceDefinitions(repositoryRoot);
const ownedProcesses = [];
let shuttingDown = false;

await main();

async function main() {
  await mkdir(logRoot, { recursive: true });
  try {
    if (native) checkWorkspaceLinks(repositoryRoot);
    // Everything that does not depend on another service starts together.
    await ensureService(services.orchestrator);
    if (services.planAgent) await ensureService(services.planAgent);
    await settleStartup([
      () => ensureService(services.pascalMcp),
      ...(services.dwg ? [() => ensureService(services.dwg)] : []),
      () => ensureService(services.editor),
    ]);
    // The backend reads PASCAL_MCP_URL when it publishes, so bring it up after.
    await ensureService(services.backend);
    if (native) {
      const response = await fetch(`${services.editor.publicUrl}/api/v1/platform/projects`, { signal: AbortSignal.timeout(10_000) });
      if (!response.ok || !Array.isArray(await response.json())) {
        throw new Error('Native Editor-to-backend project route failed after service readiness.');
      }
      console.log(`\nEditor project API connected: ${services.editor.publicUrl}`);
      console.log('  Shared agents remain external; their execution readiness is checked separately.');
    } else {
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
    }
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
  const result = await ensureManagedService(service, {
    probe: probeService, start: startService, wait: waitForService,
  });
  if (result.action === 'external' && result.state !== 'healthy') {
    console.warn(`[unavailable] ${service.name}: ${result.detail ?? result.state}. Restore through ${service.management} operations; Editor will not restart it.`);
  } else {
    console.log(`[${result.action}] ${service.name}: ${service.healthUrl}`);
    if (result.detail) console.log(`  ${result.detail}`);
  }
  return result;
}

function startService(service) {
  if (!canManageService(service)) throw new Error(`Editor cannot manage ${service.name}`);
  const log = createWriteStream(resolve(logRoot, `${service.name}.log`), { flags: "a" });
  log.write(`\n[${new Date().toISOString()}] ${service.command} ${service.args.join(" ")}\n`);
  const child = spawn(service.command, service.args, {
    cwd: service.cwd,
    env: { ...process.env, ...service.env },
    shell: process.platform === "win32",
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  ownedProcesses.push({ ...service, created: true, pid: child.pid, child, log });
  child.stdout.on("data", (chunk) => writeServiceOutput(service.name, chunk, log, false));
  child.stderr.on("data", (chunk) => writeServiceOutput(service.name, chunk, log, true));
  child.once("error", (error) => { child.spawnFailed = true; log.write(`[spawn-error] ${error.message}\n`); });
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
