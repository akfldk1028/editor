import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import test from 'node:test';

import { isAlive, killTree } from './processes.mjs';
import { hostPaths, readRecord } from './state.mjs';
import { Supervisor } from './supervise.mjs';

// A tiny HTTP service the supervisor can launch from a temp "ACE root": answers /health with
// its pid and the token it got from the env file the registry entry names.
const SERVER = `
  const port = Number(process.argv[process.argv.indexOf('--port') + 1]);
  require('node:http').createServer((request, response) => {
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ ok: true, pid: process.pid, token: process.env.FAKE_TOKEN ?? null }));
  }).listen(port, '127.0.0.1');
  setInterval(() => {}, 1 << 30);
`;

const FAST = { intervalMs: 100, failureThreshold: 2, backoffMs: [100, 200], healthyResetMs: 1_000, startupGraceMs: 3_000 };
const sleep = ms => new Promise(done => setTimeout(done, ms));

async function freePort() {
  const server = createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address();
  await new Promise(done => server.close(done));
  return port;
}

async function health(port) {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(500) });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

async function waitFor(predicate, timeoutMs, step = 50) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value) return value;
    await sleep(step);
  }
  throw new Error(`condition not met within ${timeoutMs} ms`);
}

function fixture() {
  const root = mkdtempSync(resolve(tmpdir(), 'ace-host-'));
  mkdirSync(resolve(root, 'svc'));
  writeFileSync(resolve(root, 'svc/server.cjs'), SERVER);
  writeFileSync(resolve(root, 'svc/service.env'), '# token\nexport FAKE_TOKEN="from-env-file"\n');
  const paths = hostPaths(resolve(root, 'editor'));
  const entryFor = port => ({
    id: 'fake', kind: 'editor', owner_repo: 'editor', lifecycle: 'persistent', management: 'editor-session',
    host_env: null, port, health_url: '{base}/health', card_url: null, depends_on: [], version_source: null, notes: '',
    start: { cwd: 'svc', cmd: [process.execPath, 'server.cjs', '--port', '{port}'], env_file: 'service.env' },
  });
  const cleanup = () => {
    const record = readRecord(paths, 'fake');
    if (record) killTree(record.pid);
    rmSync(root, { recursive: true, force: true });
  };
  return { root, paths, entryFor, cleanup };
}

test('launches detached from the registry command with the env file, then restarts a killed service within the policy window', async () => {
  const { root, paths, entryFor, cleanup } = fixture();
  const port = await freePort();
  const entry = entryFor(port);
  const log = [];
  const supervisor = new Supervisor([entry], () => ['fake'], { root, paths, policy: FAST, log: line => log.push(line) });
  const loop = supervisor.run();
  try {
    const first = await waitFor(() => health(port), 5_000);
    const record = readRecord(paths, 'fake');
    assert.equal(record.pid, first.pid, 'pid record is the listening process');
    assert.equal(record.adopted, false);
    assert.deepEqual(record.cmd.slice(-2), ['--port', String(port)]);
    assert.equal(first.token, 'from-env-file', 'env_file lines reach the child');
    assert.ok(existsSync(paths.log('fake')) && existsSync(paths.err('fake')), 'stdout/stderr files exist');

    const killedAt = Date.now();
    killTree(first.pid);
    const second = await waitFor(async () => {
      const body = await health(port);
      return body && body.pid !== first.pid ? body : null;
    }, 5_000);
    const recovered = Date.now() - killedAt;
    // tick (<= 100 ms) + first backoff 100 ms + node start-up: well inside a second.
    assert.ok(recovered < 2_500, `restart took ${recovered} ms`);
    assert.equal(readRecord(paths, 'fake').pid, second.pid);
    assert.ok(log.some(line => line.startsWith('[restart] fake')), log.join('\n'));
    assert.ok(!isAlive(first.pid), 'the killed process is gone');
  } finally {
    supervisor.halt();
    await loop;
    cleanup();
  }
});

test('adopts a live listener instead of starting a duplicate, and reuses a live pid record', async () => {
  const { root, paths, entryFor, cleanup } = fixture();
  const port = await freePort();
  const entry = entryFor(port);
  const foreign = spawn(process.execPath, [resolve(root, 'svc/server.cjs'), '--port', String(port)], { stdio: 'ignore', windowsHide: true });
  let spawns = 0;
  const supervisor = new Supervisor([entry], () => ['fake'], {
    root, paths, policy: FAST, processes: { spawnDetached: () => { spawns++; return 0; } },
  });
  try {
    await waitFor(() => health(port), 5_000);
    const actions = await supervisor.tick();
    assert.deepEqual(actions, [{ id: 'fake', action: 'none', up: true, pid: foreign.pid }]);
    const record = readRecord(paths, 'fake');
    assert.equal(record.pid, foreign.pid);
    assert.equal(record.adopted, true);
    assert.equal(spawns, 0, 'nothing launched while the port is served');
    // Second look: the record is live, so the supervisor neither re-adopts nor starts.
    assert.equal((await supervisor.tick())[0].action, 'none');
    assert.equal(spawns, 0);
    // stop() kills the adopted tree and forgets it.
    supervisor.stop(entry);
    assert.equal(readRecord(paths, 'fake'), null);
    await waitFor(async () => !(await health(port)), 3_000);
  } finally {
    if (foreign.exitCode === null) foreign.kill();
    cleanup();
  }
});

test('a service nobody wants any more drops out of the loop without being killed', async () => {
  const { root, paths, entryFor, cleanup } = fixture();
  const port = await freePort();
  const entry = entryFor(port);
  let wanted = ['fake'];
  const supervisor = new Supervisor([entry], () => wanted, { root, paths, policy: FAST });
  try {
    assert.equal((await supervisor.tick())[0].action, 'start');
    const body = await waitFor(() => health(port), 5_000);
    wanted = [];
    assert.deepEqual(await supervisor.tick(), []);
    assert.ok(isAlive(body.pid), 'forgetting is not stopping');
    assert.equal(readRecord(paths, 'fake').pid, body.pid, 'the pid record stays for `host stop`');
    assert.match(readFileSync(paths.record('fake'), 'utf8'), /"adopted": false/);
  } finally {
    cleanup();
  }
});

test('a missing executable does not kill the loop: the tick survives, the spawn error is in the ledger, and the health snapshot is written', async () => {
  const { root, paths, entryFor, cleanup } = fixture();
  const port = await freePort();
  const entry = { ...entryFor(port), id: 'ghost', start: { cwd: 'svc', cmd: ['no-such-executable-xyz', '--port', '{port}'], env_file: null } };
  const log = [];
  const supervisor = new Supervisor([entry], () => ['ghost'], { root, paths, policy: FAST, log: line => log.push(line) });
  try {
    const first = await supervisor.tick();
    assert.equal(first[0].action, 'start');
    await sleep(300);
    const second = await supervisor.tick();
    assert.ok(['none', 'wait', 'restart'].includes(second[0].action), JSON.stringify(second));
    assert.ok(log.some(line => line.startsWith('[spawn-error] ghost: ENOENT')), log.join('\n'));
    const events = readFileSync(paths.events, 'utf8').trim().split('\n').map(line => JSON.parse(line));
    assert.ok(events.some(event => event.kind === 'spawn-error' && event.id === 'ghost' && event.error === 'ENOENT'));
    const snapshot = JSON.parse(readFileSync(resolve(paths.runtime, 'health.json'), 'utf8'));
    assert.equal(snapshot.services.ghost.up, false);
    assert.ok(['down', 'starting', 'restarting'].includes(snapshot.services.ghost.state));
  } finally {
    supervisor.halt();
    const record = readRecord(paths, 'ghost');
    if (record?.pid) killTree(record.pid);
    rmSync(root, { recursive: true, force: true });
    cleanup();
  }
});

test('a tick probes every entry in parallel: two slow probes cost one probe time, not two', async () => {
  const { root, paths, entryFor, cleanup } = fixture();
  const entries = [{ ...entryFor(1), id: 'a' }, { ...entryFor(2), id: 'b' }];
  const probe = async () => { await sleep(300); return { up: true, status: 200, latencyMs: 300 }; };
  const supervisor = new Supervisor(entries, () => ['a', 'b'], { root, paths, policy: FAST, probe, processes: { listenerPid: () => 4242, processStartTime: () => null, isAlive: () => true } });
  try {
    const started = Date.now();
    const actions = await supervisor.tick();
    const took = Date.now() - started;
    assert.deepEqual(actions.map(action => [action.id, action.action, action.up]), [['a', 'none', true], ['b', 'none', true]]);
    assert.ok(took < 550, `tick took ${took} ms`);
  } finally {
    cleanup();
  }
});


test('an up entry with idle_timeout_s and no lease is stopped and forgotten after the timeout, with an idle-stop event', async () => {
  const { root, paths, entryFor, cleanup } = fixture();
  const port = await freePort();
  const entry = { ...entryFor(port), idle_timeout_s: 60 };
  const forgotten = [];
  const log = [];
  const policy = { ...FAST, minUpMs: 0 };
  const supervisor = new Supervisor([entry], () => (forgotten.includes('fake') ? [] : ['fake']), { root, paths, policy, log: line => log.push(line), forget: ids => forgotten.push(...ids) });
  try {
    await supervisor.tick();
    const first = await waitFor(() => health(port), 5_000);
    // A tick 61 s "later": the lease never existed, so idle since start -> stopped and forgotten.
    const actions = await supervisor.tick(Date.now() + 61_000);
    assert.equal(actions[0].up, true);
    assert.deepEqual(forgotten, ['fake']);
    assert.ok(log.some(line => line.startsWith('[idle-stop] fake')), log.join('\n'));
    await waitFor(async () => !(await health(port)), 3_000);
    assert.ok(!isAlive(first.pid));
    const snapshot = JSON.parse(readFileSync(resolve(paths.runtime, 'health.json'), 'utf8'));
    assert.equal(snapshot.services.fake.state, 'down');
  } finally {
    supervisor.halt();
    cleanup();
  }
});
