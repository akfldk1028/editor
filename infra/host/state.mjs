// Files the host keeps between runs under runtime/host (pid records, the wanted set, the
// daemon's own record) and where service output lands (logs/host). Both are gitignored.
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const EDITOR_ROOT = fileURLToPath(new URL('../..', import.meta.url));
export const ACE_ROOT = resolve(EDITOR_ROOT, '..');

export function hostPaths(root = EDITOR_ROOT) {
  const runtime = resolve(root, 'runtime/host');
  const logs = resolve(root, 'logs/host');
  return {
    runtime,
    logs,
    daemon: resolve(runtime, 'daemon.json'),
    wanted: resolve(runtime, 'wanted.json'),
    // The daemon's last tick: {at, services: {id: {up, pid, state, failures, restarts}}}; readers trust it for a few seconds.
    health: resolve(runtime, 'health.json'),
    // One JSON line per lifecycle event (start, adopt, restart, stop, spawn-error, gave-up, ensure, idle-stop).
    events: resolve(runtime, 'events.jsonl'),
    // {id: {until: ISO}}: "someone is using it until then" (ensure/touch); idle stops wait for the lease to end.
    leases: resolve(runtime, 'leases.json'),
    record: id => resolve(runtime, `${id}.json`),
    log: id => resolve(logs, `${id}.log`),
    err: id => resolve(logs, `${id}.err`),
  };
}

export function ensureDirs(paths) {
  mkdirSync(paths.runtime, { recursive: true });
  mkdirSync(paths.logs, { recursive: true });
}

export function readJson(path) {
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

export function writeJson(path, value) {
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
}

export function remove(path) {
  rmSync(path, { force: true });
}

/** {pid, startedAt, cmd, adopted} for a service, or null when the host never started/adopted it. */
export function readRecord(paths, id) {
  return readJson(paths.record(id));
}

export function writeRecord(paths, id, record) {
  writeJson(paths.record(id), record);
}

export function readLeases(paths) {
  return readJson(paths.leases) ?? {};
}

/** Extends (never shortens) the lease of each id to now + seconds. */
export function extendLeases(paths, ids, seconds, now = Date.now()) {
  const leases = readLeases(paths);
  const until = new Date(now + seconds * 1000).toISOString();
  for (const id of ids) {
    if (!leases[id] || Date.parse(leases[id].until) < now + seconds * 1000) leases[id] = { until };
  }
  writeJson(paths.leases, leases);
  return until;
}

export function readHealth(paths) {
  return readJson(paths.health);
}

export function writeHealth(paths, snapshot) {
  writeJson(paths.health, snapshot);
}

export function appendEvent(paths, event) {
  appendFileSync(paths.events, JSON.stringify({ at: new Date().toISOString(), ...event }) + '\n');
}

export function readWanted(paths) {
  return readJson(paths.wanted)?.ids ?? [];
}

export function writeWanted(paths, ids) {
  writeJson(paths.wanted, { ids: [...new Set(ids)] });
}

/** Service ids that have a pid record on disk. */
export function recordedIds(paths) {
  if (!existsSync(paths.runtime)) return [];
  return readdirSync(paths.runtime)
    .filter(name => name.endsWith('.json') && !['daemon.json', 'wanted.json', 'health.json', 'leases.json'].includes(name))
    .map(name => name.slice(0, -'.json'.length));
}
