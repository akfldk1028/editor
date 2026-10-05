import assert from 'node:assert/strict';
import test from 'node:test';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { ensureService, settleStartup, canManageService } from './lifecycle.mjs';
import { createServiceDefinitions, stopOwnedProcesses } from './runtime.mjs';

const session = { name: 'test', source_owner: 'editor', lifecycle: 'session', management: 'editor-session' };
const shared = { name: 'agent', source_owner: 'agents', lifecycle: 'persistent', management: 'agent-host' };

test('test_shared_offline_never_spawns', async () => {
  for (const state of ['offline', 'occupied', 'healthy']) {
    const result = await ensureService(shared, {
      probe: async () => ({ state }),
      start: () => assert.fail('shared service spawned'),
    });
    assert.equal(result.state, state);
  }
});

test('test_shutdown_leaves_shared_and_reused_services_running', async () => {
  const stopped = [];
  await stopOwnedProcesses([
    { ...session, name: 'created', created: true },
    { ...session, name: 'reused', created: false },
    { ...shared, created: true },
    { name: 'unknown', created: true },
  ], async item => stopped.push(item.name));
  assert.deepEqual(stopped, ['created']);
});

test('test_ui_exit_keeps_domain_host_alive', async () => {
  const domain = { ...session, lifecycle: 'persistent', management: 'domain-host' };
  assert.equal(canManageService(domain), false);
  await ensureService(domain, { probe: async () => ({ state: 'offline' }), start: () => assert.fail('domain spawned') });
  await stopOwnedProcesses([{ ...domain, created: true }], () => assert.fail('domain stopped'));
});

test('healthy session is reused; offline session starts and waits; occupied port rejects', async () => {
  let starts = 0;
  const operations = { probe: async () => ({ state: 'offline' }), start: () => { starts++; return { exitCode: null }; }, wait: async () => ({ state: 'healthy' }) };
  assert.equal((await ensureService(session, operations)).action, 'started');
  assert.equal(starts, 1);
  assert.equal((await ensureService(session, { ...operations, probe: async () => ({ state: 'healthy' }) })).action, 'reused');
  await assert.rejects(ensureService(session, { ...operations, probe: async () => ({ state: 'occupied' }) }), /incompatible/);
  assert.equal(starts, 1);
  await assert.rejects(ensureService(session, { ...operations, wait: async () => ({ state: 'timeout' }) }), /ready/);
});

test('startup failure waits for sibling startup before cleanup', async () => {
  const events = [];
  await assert.rejects(settleStartup([
    async () => { throw new Error('failed'); },
    async () => { await new Promise(resolve => setTimeout(resolve, 10)); events.push('started'); },
  ]), /failed/);
  events.push('cleanup');
  assert.deepEqual(events, ['started', 'cleanup']);
});

test('registry makes the external owner probe-only without a launch command', () => {
  const services = createServiceDefinitions(process.cwd());
  assert.equal(canManageService(services.orchestrator), false);
  assert.equal(services.orchestrator.management, 'agent-host');
  assert.equal(services.orchestrator.command, undefined);
  // The Plan Agent (agents/planm) is another external owner: probed, never launched from here.
  assert.equal(canManageService(services.planAgent), false);
  assert.equal(services.planAgent.command, undefined);
  assert.ok(services.planAgent.validate({ body: { agent: 'plan', tools: ['plan_stage', 'plan_generate'] } }));
  assert.ok(!services.planAgent.validate({ body: { agent: 'plan', tools: ['plan_health'] } }));
  for (const [name, service] of Object.entries(services)) {
    if (!['orchestrator', 'arr', 'planAgent'].includes(name)) assert.equal(canManageService(service), true, name);
  }
});

test('ARR host is probe-only and reports law dependency readiness separately', () => {
  const { arr } = createServiceDefinitions(process.cwd());
  assert.ok(arr, 'ARR must have an explicit lifecycle registration');
  assert.equal(canManageService(arr), false);
  assert.equal(arr.command, undefined);
  assert.equal(arr.healthUrl, `${process.env.EDITOR_ARR_URL || 'http://127.0.0.1:18320'}/law/health/`);
  assert.ok(arr.validate({ body: { status: 'ok', django: true, ready: false } }));
  assert.ok(!arr.validate({ body: { status: 'ok' } }));
  assert.match(arr.describe({ body: { status: 'ok', django: true, ready: false } }), /unavailable/);
});

for (const failure of [false, true]) {
  test(`isolated HTTP processes survive ${failure ? 'startup failure' : 'session shutdown'} according to ownership`, async () => {
    const children = [];
    const launch = async policy => {
      const child = spawn(process.execPath, ['-e', `
        require('node:http').createServer((req,res)=>res.end('alive'))
          .listen(0,'127.0.0.1',function(){process.send(this.address().port)});
      `], { windowsHide: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc'] });
      children.push(child);
      const [port] = await once(child, 'message');
      return { ...policy, child, pid: child.pid, url: `http://127.0.0.1:${port}` };
    };
    const terminate = async ({ child }) => {
      if (child.exitCode !== null || child.signalCode !== null) return;
      const exited = once(child, 'exit');
      child.kill();
      await exited;
    };
    try {
      const owned = await launch({ ...session, created: true });
      const reused = await launch({ ...session, created: false });
      const domain = await launch({ ...session, lifecycle: 'persistent', management: 'domain-host', created: false });
      const agent = await launch({ ...shared, created: false });
      if (failure) await assert.rejects(settleStartup([async () => { throw new Error('startup failed'); }]), /startup failed/);
      await stopOwnedProcesses([owned, reused, domain, agent], terminate);
      await assert.rejects(fetch(owned.url));
      for (const service of [reused, domain, agent]) assert.equal(await (await fetch(service.url)).text(), 'alive');
    } finally {
      await Promise.all(children.map(child => terminate({ child })));
    }
  });
}
