// The supervisor: adopts or launches registry entries detached, watches their health and
// restarts them under policy.mjs. All I/O lives here; decisions come from policy.mjs.
import { resolve } from 'node:path';
import { DEFAULTS, decide, describeState, idleStops, initialState, nextTickMs, selectEntries, startOrder } from './policy.mjs';
import { probe as probeEntry } from './probe.mjs';
import * as os from './processes.mjs';
import { startCommand } from './registry.mjs';
import { ACE_ROOT, appendEvent, ensureDirs, hostPaths, readLeases, readRecord, remove, writeHealth, writeRecord } from './state.mjs';

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
    // forget(ids): take idle-stopped ids out of the wanted set (the CLI wires this to wanted.json).
    this.forget = options.forget ?? (() => {});
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
    this.event('adopt', entry.id, { pid, port: entry.port }, `[adopt] ${entry.id}: pid ${pid} already listens on ${entry.port}`);
    return { record: adopted, alive: true };
  }

  async observe(entry) {
    const { record, alive } = this.locate(entry);
    const health = await this.probe(entry, this.env);
    return { record, health, known: record !== null, alive, up: health.up === true };
  }

  /** One look at every wanted entry: probes run in parallel (a tick costs one probe timeout, not n of them),
   *  decisions apply in start order, then the health snapshot is written for status/ensure to read. Entries the
   *  host does not keep (compose containers, processes someone else started) are probed too, so the snapshot says
   *  who is up across the whole registry: 'up' or 'absent', never a decision. */
  async tick(now = Date.now()) {
    const actions = [];
    const entries = this.entries();
    const others = this.services.filter(entry => entry.health_url && !entries.some(kept => kept.id === entry.id));
    const [observations, elsewhere] = await Promise.all([
      Promise.all(entries.map(entry => this.observe(entry))),
      Promise.all(others.map(entry => this.probe(entry, this.env))),
    ]);
    const snapshot = { at: new Date(now).toISOString(), services: {} };
    others.forEach((entry, index) => {
      const health = elsewhere[index];
      snapshot.services[entry.id] = { up: health.up === true, pid: null, state: health.up === true ? 'up' : 'absent',
        failures: 0, restarts: 0, version: health.version ?? null, managed: false };
    });
    entries.forEach((entry, index) => {
      if (this.stopped) return;
      const observation = observations[index];
      const state = this.states.get(entry.id) ?? initialState();
      const decision = decide(state, observation, now, this.policy);
      this.states.set(entry.id, decision.state);
      if (decision.action === 'start') this.start(entry);
      if (decision.action === 'restart') this.restart(entry, observation.record);
      if (decision.action === 'wait') this.log(`[wait] ${entry.id}: restart due in ${Math.max(0, decision.state.dueAt - now)} ms`);
      if (decision.action === 'give-up') {
        this.event('gave-up', entry.id, { restarts: decision.state.restarts, error: observation.health.error ?? null },
          `[gave-up] ${entry.id}: ${decision.state.restarts} restarts without health; restart ${entry.id} by hand to try again`);
      }
      const pid = observation.alive ? observation.record.pid : null;
      actions.push({ id: entry.id, action: decision.action, up: observation.up, pid });
      snapshot.services[entry.id] = { up: observation.up, pid, state: describeState(decision.state, observation),
        failures: decision.state.failures, restarts: decision.state.restarts, version: observation.health.version ?? null, managed: true };
    });
    const ups = new Set(entries.filter((entry, index) => observations[index].up).map(entry => entry.id));
    const records = Object.fromEntries(entries.map((entry, index) => [entry.id, observations[index].record]));
    const idle = this.stopped ? [] : idleStops(entries, { ups, leases: readLeases(this.paths), records }, now, this.policy);
    for (const id of idle) {
      const entry = entries.find(candidate => candidate.id === id);
      this.event('idle-stop', id, { pid: records[id]?.pid ?? null, idle_timeout_s: entry.idle_timeout_s }, `[idle-stop] ${id}: no lease for ${entry.idle_timeout_s} s`);
      this.stop(entry);
      snapshot.services[id] = { ...snapshot.services[id], up: false, pid: null, state: 'down' };
    }
    if (idle.length) this.forget(idle);
    writeHealth(this.paths, snapshot);
    return actions;
  }

  /** A lifecycle event: one JSON line in events.jsonl plus the human log line. */
  event(kind, id, detail = {}, line = null) {
    try { appendEvent(this.paths, { kind, id, ...detail }); } catch { /* the ledger never stops the loop */ }
    if (line) this.log(line);
  }

  start(entry) {
    const cmd = startCommand(entry);
    const cwd = resolve(this.root, entry.start.cwd);
    const fileEnv = entry.start.env_file ? this.os.readEnvFile(resolve(cwd, entry.start.env_file)) : {};
    const pid = this.os.spawnDetached(cmd[0], cmd.slice(1), {
      cwd, env: { ...this.env, ...fileEnv }, logPath: this.paths.log(entry.id), errPath: this.paths.err(entry.id),
      onError: error => this.event('spawn-error', entry.id, { error: error?.code ?? String(error) }, `[spawn-error] ${entry.id}: ${error?.code ?? error}`),
    });
    const record = { pid, startedAt: new Date().toISOString(), cmd, adopted: false };
    writeRecord(this.paths, entry.id, record);
    this.event('start', entry.id, { pid, cmd }, `[start] ${entry.id}: pid ${pid} <- ${cmd.join(' ')}`);
    return record;
  }

  restart(entry, record) {
    const alive = record && this.os.isAlive(record.pid);
    if (alive) this.os.killTree(record.pid);
    remove(this.paths.record(entry.id));
    this.event('restart', entry.id, { pid: record?.pid ?? null, alive }, `[restart] ${entry.id}: ${alive ? `killed pid ${record.pid}` : `pid ${record?.pid ?? '-'} was gone`}`);
    return this.start(entry);
  }

  stop(entry) {
    const record = readRecord(this.paths, entry.id);
    if (record) this.os.killTree(record.pid);
    remove(this.paths.record(entry.id));
    this.states.delete(entry.id);
    this.event('stop', entry.id, { pid: record?.pid ?? null }, `[stop] ${entry.id}: pid ${record?.pid ?? '-'}`);
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
