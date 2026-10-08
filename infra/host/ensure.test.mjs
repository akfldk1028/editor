import assert from 'node:assert/strict';
import test from 'node:test';

import { waitHealthy } from './ensure.mjs';

const entries = [{ id: 'law' }, { id: 'mass' }, { id: 'neo4j' }];

test('waitHealthy returns once every entry answers, keeps entry order, and counts entries without a health URL as up', async () => {
  const answers = { law: [false, true], mass: [false, false, true], neo4j: [null] };
  const calls = { law: 0, mass: 0, neo4j: 0 };
  const probeImpl = async entry => {
    const up = answers[entry.id][Math.min(calls[entry.id]++, answers[entry.id].length - 1)];
    return up === null ? { up: null, error: 'no health URL' } : { up, status: up ? 200 : null, error: up ? undefined : 'ECONNREFUSED' };
  };
  let clock = 0;
  const result = await waitHealthy(entries, { probeImpl, intervalMs: 10, timeoutMs: 1_000, now: () => clock, sleep: async ms => { clock += ms; } });
  assert.deepEqual(result, { up: ['law', 'mass', 'neo4j'], failed: [], waitedMs: 20 });
  assert.deepEqual(calls, { law: 2, mass: 3, neo4j: 1 });
});

test('waitHealthy gives up at the deadline and names what never answered with its last error', async () => {
  const probeImpl = async entry => (entry.id === 'law' ? { up: true, status: 200 } : { up: false, status: 503 });
  let clock = 0;
  const result = await waitHealthy(entries.slice(0, 2), { probeImpl, intervalMs: 100, timeoutMs: 250, now: () => clock, sleep: async ms => { clock += ms; } });
  assert.deepEqual(result, { up: ['law'], failed: [{ id: 'mass', error: 'status 503' }], waitedMs: 300 });
});
