// The supervisor: adopts or launches registry entries detached, watches their health and
// restarts them under policy.mjs. All I/O lives here; decisions come from policy.mjs.
import { resolve } from 'node:path';
import { DEFAULTS, decide, initialState, nextTickMs, selectEntries, startOrder } from './policy.mjs';
import { probe as probeEntry } from './probe.mjs';
import * as os from './processes.mjs';
import { startCommand } from './registry.mjs';
import { ACE_ROOT, ensureDirs, hostPaths, readRecord, remove, writeRecord } from './state.mjs';

const sleep = ms => new Promise(done => setTimeout(done, ms));

export class Supervisor {
  /**
   * @param services   registry entries (infra/host/registry.mjs services())
   * @param wanted     () => ids to keep alive right now (re-read every tick)
   * @param options    { root, paths, env, policy, probe, processes, log, withAgents }
   */
  constructor(services, wanted, options = {}) {
    this.services = services;
    this.wanted = wanted;
    this.root = options.root ?? ACE_ROOT;
    this.paths = options.paths ?? hostPaths();
    this.env = options.env ?? process.env;
    this.policy = { ...DEFAULTS, ...(options.policy ?? {}) };
    this.probe = options.probe ?? probeEntry;
    this.os = { ...os, ...(options.processes ?? {}) };
    this.log = options.log ?? (() => {});
    this.withAgents = options.withAgents ?? false;
    this.states = new Map();
    this.stopped = false;
    ensureDirs(this.paths);
  }

  /** The wanted ids resolved and ordered; an empty list means nothing (the CLI resolves defaults). */
  entries() {
    const ids = this.wanted();
    const entries = ids.length ? selectEntries(this.services, ids, { withAgents: this.withAgents }) : [];
    for (const id of this.states.keys()) {
      if (!entries.some(entry => entry.id === id)) this.states.delete(id);
    }
    return startOrder(entries);
  }

  /** The pid record and whether it lives; a foreign listener on the entry's port is adopted first.
   *  A dead record is kept (restart() clears it) so the policy sees the crash, not a blank slate. */
  locate(entry) {
    const existing = readRecord(this.paths, entry.id);
    if (existing && this.os.isAlive(existing.pid)) return { record: existing, alive: true };
    const pid = entry.port === null ? null : this.os.listenerPid(entry.port);
    if (!pid) return { record: existing, alive: false };
    const adopted = { pid, startedAt: this.os.processStartTime(pid) ?? new Date().toISOString(), cmd: null, adopted: true };
    writeRecord(this.paths, entry.id, adopted);
    this.log(`[adopt] ${entry.id}: pid ${pid} already listens on ${entry.port}`);
    return { record: adopted, alive: true };
  }

  async observe(entry) {
    const { record, alive } = this.locate(entry);
    const health = await this.probe(entry, this.env);
    return { record, health, known: record !== null, alive, up: health.up === true };
  }

  async tick(now = Date.now()) {
    const actions = [];
    for (const entry of this.entries()) {
      if (this.stopped) break;
      const observation = await this.observe(entry);
      const state = this.states.get(entry.id) ?? initialState();
      const decision = decide(state, observation, now, this.policy);
      this.states.set(entry.id, decision.state);
      if (decision.action === 'start') this.start(entry);
      if (decision.action === 'restart') this.restart(entry, observation.record);
      if (decision.action === 'wait') this.log(`[wait] ${entry.id}: restart due in ${Math.max(0, decision.state.dueAt - now)} ms`);
      actions.push({ id: entry.id, action: decision.action, up: observation.up, pid: observation.alive ? observation.record.pid : null });
    }
    return actions;
  }

  start(entry) {
    const cmd = startCommand(entry);
    const cwd = resolve(this.root, entry.start.cwd);
    const fileEnv = entry.start.env_file ? this.os.readEnvFile(resolve(cwd, entry.start.env_file)) : {};
    const pid = this.os.spawnDetached(cmd[0], cmd.slice(1), {
      cwd, env: { ...this.env, ...fileEnv }, logPath: this.paths.log(entry.id), errPath: this.paths.err(entry.id),
    });
    const record = { pid, startedAt: new Date().toISOString(), cmd, adopted: false };
    writeRecord(this.paths, entry.id, record);
    this.log(`[start] ${entry.id}: pid ${pid} <- ${cmd.join(' ')}`);
    return record;
  }

  restart(entry, record) {
    const alive = record && this.os.isAlive(record.pid);
    if (alive) this.os.killTree(record.pid);
    remove(this.paths.record(entry.id));
    this.log(`[restart] ${entry.id}: ${alive ? `killed pid ${record.pid}` : `pid ${record?.pid ?? '-'} was gone`}`);
    return this.start(entry);
  }

  stop(entry) {
    const record = readRecord(this.paths, entry.id);
    if (record) this.os.killTree(record.pid);
    remove(this.paths.record(entry.id));
    this.states.delete(entry.id);
    this.log(`[stop] ${entry.id}: pid ${record?.pid ?? '-'}`);
    return record;
  }

  /** The health loop; resolves when halt() is called. */
  async run() {
    while (!this.stopped) {
      const now = Date.now();
      try {
        await this.tick(now);
      } catch (error) {
        this.log(`[error] ${error instanceof Error ? error.message : String(error)}`);
      }
      await sleep(nextTickMs([...this.states.values()], Date.now(), this.policy));
    }
  }

  halt() {
    this.stopped = true;
  }
}
