import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import test from 'node:test';

import { probe } from './probe.mjs';

/** A fake service on an ephemeral loopback port; `routes` maps path -> [status, body]. */
async function fakeService(routes) {
  const server = createServer((request, response) => {
    const route = routes[request.url];
    if (!route) { response.writeHead(404); response.end(); return; }
    const [status, body, delay = 0] = route;
    setTimeout(() => {
      response.writeHead(status, { 'content-type': 'application/json' });
      response.end(JSON.stringify(body));
    }, delay);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address();
  return { port, close: () => new Promise(done => server.close(done)) };
}

const entry = (port, overrides = {}) => ({
  id: 'fake', kind: 'agent', host_env: null, port,
  health_url: '{base}/health', card_url: '{base}/.well-known/agent-card.json', version_source: 'card:version', ...overrides,
});

test('up: 200 with version and started_at from the health JSON', async () => {
  const service = await fakeService({ '/health': [200, { status: 'ok', version: 'abc123', started_at: '2026-10-08T01:00:00Z' }] });
  try {
    const result = await probe(entry(service.port), {});
    assert.equal(result.up, true);
    assert.equal(result.status, 200);
    assert.equal(result.version, 'abc123');
    assert.equal(result.startedAt, '2026-10-08T01:00:00Z');
    assert.ok(result.latencyMs >= 0);
    assert.equal(result.error, undefined);
  } finally {
    await service.close();
  }
});

test('version falls back to git_sha, then to the agent card when version_source says card:version', async () => {
  const service = await fakeService({
    '/health': [200, { ok: true }],
    '/.well-known/agent-card.json': [200, { name: 'Fake', version: '2.1.0' }],
  });
  try {
    assert.equal((await probe(entry(service.port), {})).version, '2.1.0');
    assert.equal((await probe(entry(service.port, { version_source: 'health:version' }), {})).version, undefined);
  } finally {
    await service.close();
  }
  const sha = await fakeService({ '/health': [200, { git_sha: 'deadbeef' }] });
  try {
    assert.equal((await probe(entry(sha.port), {})).version, 'deadbeef');
  } finally {
    await sha.close();
  }
});

test('down: 5xx answers are down with their status; a closed port is down with an error code', async () => {
  const service = await fakeService({ '/health': [503, { status: 'degraded' }] });
  try {
    const result = await probe(entry(service.port), {});
    assert.equal(result.up, false);
    assert.equal(result.status, 503);
  } finally {
    await service.close();
  }
  const closed = await probe(entry(service.port), {});
  assert.equal(closed.up, false);
  assert.equal(closed.status, null);
  assert.match(closed.error, /ECONNREFUSED|ECONNRESET|fetch failed/);
});

test('a probe that exceeds the timeout is down, not hung', async () => {
  const service = await fakeService({ '/health': [200, { ok: true }, 400] });
  try {
    const result = await probe(entry(service.port), {}, { timeoutMs: 50 });
    assert.equal(result.up, false);
    assert.match(result.error, /Timeout|Abort/i);
    assert.ok(result.latencyMs < 1_000);
  } finally {
    await service.close();
  }
});

test('host_env override is honoured and a service without a health URL is n/a', async () => {
  const service = await fakeService({ '/health': [200, { ok: true }] });
  try {
    const result = await probe(entry(1, { host_env: 'FAKE_URL' }), { FAKE_URL: `http://127.0.0.1:${service.port}/` });
    assert.equal(result.up, true);
  } finally {
    await service.close();
  }
  const neo4j = await probe({ id: 'neo4j', host_env: null, port: 7687, health_url: null, card_url: null }, {});
  assert.equal(neo4j.up, null);
});
