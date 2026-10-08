#!/usr/bin/env node
// agent-host: node infra/host/cli.mjs start [ids...] [--with-agents] | stop [ids...] | status | restart <id> | daemon
// `start` launches a detached daemon (this file, `daemon`) that owns the health loop and
// survives the shell that started it; `stop` kills it through runtime/host/daemon.json;
// `status` probes directly and needs no daemon.
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { selectEntries } from './policy.mjs';
import { isAlive, killTree, spawnDetached } from './processes.mjs';
import { byId, services } from './registry.mjs';
import { ensureDirs, hostPaths, readJson, readRecord, readWanted, recordedIds, remove, writeJson, writeWanted } from './state.mjs';
import { formatTable, statusRows } from './status.mjs';
import { Supervisor } from './supervise.mjs';

const SELF = fileURLToPath(import.meta.url);
const paths = hostPaths();
const sleep = ms => new Promise(done => setTimeout(done, ms));
const stamp = () => new Date().toISOString();

export function parseArgs(argv) {
  const flags = new Set(argv.filter(arg => arg.startsWith('--')));
  const [command = 'status', ...ids] = argv.filter(arg => !arg.startsWith('--'));
  return { command, ids, withAgents: flags.has('--with-agents') };
}

function daemonPid() {
  const pid = readJson(paths.daemon)?.pid;
  return pid && isAlive(pid) ? pid : null;
}

async function status(ids = []) {
  const rows = await statusRows(ids.length ? ids.map(byId) : services(), paths);
  console.log(formatTable(rows));
  const pid = daemonPid();
  console.log(`\ndaemon: ${pid ? `pid ${pid}, keeping [${readWanted(paths).join(', ')}]` : 'not running'}  (pid? = listener the host did not start)`);
}

async function start(ids, withAgents) {
  ensureDirs(paths);
  const entries = selectEntries(services(), ids, { withAgents });
  const wanted = [...new Set([...readWanted(paths), ...entries.map(entry => entry.id)])];
  writeWanted(paths, wanted);
  let pid = daemonPid();
  if (pid) {
    console.log(`daemon pid ${pid} already runs; it now keeps [${wanted.join(', ')}]`);
  } else {
    const args = [SELF, 'daemon', ...(withAgents ? ['--with-agents'] : [])];
    pid = spawnDetached(process.execPath, args, { cwd: paths.runtime, env: process.env, logPath: paths.log('daemon'), errPath: paths.err('daemon') });
    console.log(`daemon started: pid ${pid}, log ${paths.log('daemon')}`);
  }
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline && !entries.every(entry => readRecord(paths, entry.id))) await sleep(500);
  await status(entries.map(entry => entry.id));
}

function stop(ids) {
  const pid = daemonPid();
  const wanted = readWanted(paths);
  const targets = ids.length ? ids : [...new Set([...wanted, ...recordedIds(paths)])];
  const remaining = wanted.filter(id => !targets.includes(id));
  if (pid && remaining.length === 0) {
    killTree(pid);
    remove(paths.daemon);
    console.log(`daemon pid ${pid} stopped`);
  }
  writeWanted(paths, remaining);
  for (const id of targets) {
    const record = readRecord(paths, id);
    if (record) killTree(record.pid);
    remove(paths.record(id));
    console.log(`[stop] ${id}: ${record ? `pid ${record.pid}` : 'no record'}`);
  }
  if (pid && remaining.length) console.log(`daemon pid ${pid} keeps [${remaining.join(', ')}]`);
}

async function restart(id) {
  const entry = byId(id);
  const record = readRecord(paths, id);
  if (record) killTree(record.pid);
  remove(paths.record(id));
  console.log(`[restart] ${id}: killed ${record ? `pid ${record.pid}` : 'nothing'}`);
  if (daemonPid() && readWanted(paths).includes(id)) {
    console.log('the daemon relaunches it on its next tick (within 10 s + backoff)');
    return;
  }
  new Supervisor(services(), () => [id], { log: console.log }).start(entry);
  await status([id]);
}

async function daemon(withAgents) {
  ensureDirs(paths);
  writeJson(paths.daemon, { pid: process.pid, startedAt: stamp(), withAgents });
  const supervisor = new Supervisor(services(), () => readWanted(paths), { withAgents, log: line => console.log(`${stamp()} ${line}`) });
  const halt = () => { supervisor.halt(); remove(paths.daemon); process.exit(0); };
  process.on('SIGINT', halt);
  process.on('SIGTERM', halt);
  console.log(`${stamp()} [daemon] pid ${process.pid} keeping [${readWanted(paths).join(', ')}]`);
  await supervisor.run();
  remove(paths.daemon);
}

async function main(argv) {
  const { command, ids, withAgents } = parseArgs(argv);
  switch (command) {
    case 'status': return status(ids);
    case 'start': return start(ids, withAgents);
    case 'stop': return stop(ids);
    case 'restart':
      if (ids.length !== 1) throw new Error('usage: restart <id>');
      return restart(ids[0]);
    case 'daemon': return daemon(withAgents);
    default: throw new Error(`unknown command "${command}"; use start|stop|status|restart`);
  }
}

const invoked = process.argv[1] ? resolve(process.argv[1]) : '';
const same = process.platform === 'win32' ? invoked.toLowerCase() === SELF.toLowerCase() : invoked === SELF;
if (same) {
  main(process.argv.slice(2)).catch(error => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
