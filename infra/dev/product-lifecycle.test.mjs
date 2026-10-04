import assert from 'node:assert/strict';
import test from 'node:test';
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
  for (const [name, service] of Object.entries(services)) {
    if (name !== 'orchestrator') assert.equal(canManageService(service), true, name);
  }
});
