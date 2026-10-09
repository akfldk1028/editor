// OS-facing helpers for the supervisor: who listens on a port, is a pid alive, launch a
// detached child whose output goes to files, kill a process tree. Node built-ins only.
import { spawn, spawnSync } from 'node:child_process';
import { closeSync, existsSync, openSync, readFileSync } from 'node:fs';
import { isAbsolute, resolve } from 'node:path';

const win32 = process.platform === 'win32';

/** Map of TCP port -> pid for every listening socket on this machine (one netstat/lsof call). */
export function listeningPorts() {
  const ports = new Map();
  if (win32) {
    const out = spawnSync('netstat', ['-ano', '-p', 'tcp'], { encoding: 'utf8', windowsHide: true }).stdout ?? '';
    for (const line of out.split(/\r?\n/)) {
      const match = line.match(/^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)\s*$/);
      if (match && !ports.has(Number(match[1]))) ports.set(Number(match[1]), Number(match[2]));
    }
    return ports;
  }
  const out = spawnSync('lsof', ['-nP', '-iTCP', '-sTCP:LISTEN', '-Fpn'], { encoding: 'utf8' }).stdout ?? '';
  let pid = null;
  for (const line of out.split('\n')) {
    if (line.startsWith('p')) pid = Number(line.slice(1));
    const port = line.startsWith('n') ? Number(line.slice(line.lastIndexOf(':') + 1)) : NaN;
    if (pid && Number.isInteger(port) && !ports.has(port)) ports.set(port, pid);
  }
  return ports;
}

/** pid of the process listening on `port`, or null. */
export function listenerPid(port) {
  return listeningPorts().get(port) ?? null;
}

export function isAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

/** ISO creation time of a live process when the OS tells us (Windows: CIM); otherwise null. */
export function processStartTime(pid) {
  if (!win32) return null;
  const script = `(Get-CimInstance Win32_Process -Filter 'ProcessId=${Number(pid)}').CreationDate.ToUniversalTime().ToString('o')`;
  const out = spawnSync('powershell', ['-NoProfile', '-Command', script], { encoding: 'utf8', windowsHide: true, timeout: 10_000 }).stdout ?? '';
  const iso = out.trim();
  return Number.isNaN(Date.parse(iso)) ? null : iso;
}

export function killTree(pid) {
  if (!isAlive(pid)) return;
  if (win32) {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    return;
  }
  try { process.kill(-pid, 'SIGTERM'); } catch { /* not a group leader */ }
  try { process.kill(pid, 'SIGTERM'); } catch { /* already gone */ }
}

/** Ends one process and nothing it spawned: the daemon's own restart leaves its detached services running. */
export function killOne(pid) {
  if (!isAlive(pid)) return;
  if (win32) {
    spawnSync('taskkill', ['/PID', String(pid), '/F'], { stdio: 'ignore', windowsHide: true });
    return;
  }
  try { process.kill(pid, 'SIGTERM'); } catch { /* already gone */ }
}

/**
 * KEY=value lines (quotes stripped, `export ` and comments ignored); missing file -> {}. A value may
 * reference earlier keys or the process env the shell way — `${NAME}` / `${NAME:-default}` — because
 * the agents' env files are written for `source` (MassAgent: `export MASS_A2A_PORT="${MASS_A2A_PORT:-18331}"`);
 * passed literally, the server was told `--port '${MASS_A2A_PORT:-18331}'` and never came up.
 */
export function readEnvFile(path, base = process.env) {
  if (!existsSync(path)) return {};
  const env = {};
  for (const raw of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const line = raw.trim().replace(/^export\s+/, '');
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim().replace(/^(['"])(.*)\1$/, '$2');
    env[key] = expand(value, name => env[name] ?? base[name]);
  }
  return env;
}

/** Innermost `${NAME}` / `${NAME:-default}` first, repeated until none is left (defaults may nest one reference). */
function expand(value, lookup) {
  const reference = /\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^${}]*))?\}/g;
  let current = value;
  for (let round = 0; round < 8 && reference.test(current); round += 1) {
    current = current.replace(reference, (_, name, fallback) => lookup(name) ?? fallback ?? '');
  }
  return current;
}

/** Whether the Docker engine answers (`docker info`); false when the CLI is missing or Docker Desktop is off. */
export function dockerEngineUp() {
  const result = spawnSync('docker', ['info', '--format', '{{.ServerVersion}}'], { encoding: 'utf8', windowsHide: true, timeout: 10_000 });
  return result.status === 0;
}

/** `python` means the editor's own interpreter when its venv exists (the native dev runner does the same). */
export function resolveCommand(command, cwd, env = process.env) {
  if (command === 'python') {
    if (env.EDITOR_PYTHON) return env.EDITOR_PYTHON;
    const venv = resolve(cwd, '.venv', win32 ? 'Scripts/python.exe' : 'bin/python');
    if (existsSync(venv)) return venv;
  }
  if (win32 && ['npm', 'npx', 'yarn', 'pnpm'].includes(command)) return `${command}.cmd`;
  return command;
}

/**
 * Start `[command, ...args]` detached from this process: its own process group, no console,
 * stdout/stderr appended to the given files. Returns the child's pid. Node refuses to run .cmd
 * launchers without a shell, so those go through one (taskkill /T still reaches the tree).
 */
export function spawnDetached(command, args, { cwd, env, logPath, errPath, onError = null }) {
  const out = openSync(logPath, 'a');
  const err = openSync(errPath, 'a');
  const resolved = isAbsolute(command) ? command : resolveCommand(command, cwd, env);
  const shell = win32 && /\.(cmd|bat)$/i.test(resolved);
  try {
    const child = spawn(resolved, shell ? args.map(quoteForShell) : args, {
      cwd, env, shell, detached: true, windowsHide: true, stdio: ['ignore', out, err],
    });
    // A missing executable arrives as an asynchronous 'error' event; unhandled, it killed the whole daemon
    // (2026-10-08: `spawn bun ENOENT` for one entry took every supervised service's keeper down).
    child.on('error', error => { if (onError) onError(error); });
    child.unref();
    return child.pid ?? null;
  } finally {
    closeSync(out);
    closeSync(err);
  }
}

function quoteForShell(part) {
  return /\s/.test(part) ? `"${part}"` : part;
}
