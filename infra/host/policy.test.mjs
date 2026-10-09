import assert from 'node:assert/strict';
import test from 'node:test';

import { DEFAULTS, backoffMs, decide, defaultSet, describeState, idleIn, idleStops, initialState, nextTickMs, selectEntries, startOrder } from './policy.mjs';
import { services } from './registry.mjs';

const T0 = 1_000_000;
const live = { up: false, known: true, alive: true };
const dead = { up: false, known: true, alive: false };
const up = { up: true, known: true, alive: true };
const none = { up: false, known: false, alive: false };

/** Run `decide` over a sequence of [observation, now] pairs and collect the actions. */
function run(observations, state = initialState(), options = DEFAULTS) {
  const actions = [];
  for (const [observation, now] of observations) {
    const next = decide(state, observation, now, options);
    state = next.state;
    actions.push(next.action);
  }
  return { actions, state };
}

test('default set: persistent editor-owned services; Orchestrator and agents only with --with-agents', () => {
  const ids = defaultSet(services()).map(entry => entry.id).sort();
  assert.deepEqual(ids, ['backend', 'dwg', 'pascalMcp']);
  const withAgents = defaultSet(services(), { withAgents: true }).map(entry => entry.id);
  assert.ok(withAgents.includes('orchestrator') && withAgents.includes('law') && withAgents.includes('plan'));
  assert.ok(!withAgents.includes('neo4j'), 'external infrastructure is never started from here');
  assert.ok(!withAgents.includes('editor') && !withAgents.includes('frontend'), 'dev servers stay session-scoped');
});

test('explicit ids override the default set; unknown ids and unstartable services throw', () => {
  assert.deepEqual(selectEntries(services(), ['backend']).map(entry => entry.id), ['backend']);
  assert.throws(() => selectEntries(services(), ['arr']), /Unknown service/);
  const noStart = [{ id: 'x', lifecycle: 'persistent', start: null, depends_on: [] }];
  assert.throws(() => selectEntries(noStart, ['x']), /no start command/);
});

test('start order puts dependencies first, ignores dependencies outside the set, rejects cycles', () => {
  const entries = [
    { id: 'backend', depends_on: ['pascalMcp'] },
    { id: 'scene', depends_on: ['site-context'] },
    { id: 'pascalMcp', depends_on: [] },
  ];
  assert.deepEqual(startOrder(entries).map(entry => entry.id), ['pascalMcp', 'backend', 'scene']);
  assert.throws(() => startOrder([{ id: 'a', depends_on: ['b'] }, { id: 'b', depends_on: ['a'] }]), /cycle/);
  const registryOrder = startOrder(defaultSet(services())).map(entry => entry.id);
  assert.ok(registryOrder.indexOf('pascalMcp') < registryOrder.indexOf('backend'));
});

test('backoff: 5 s, 10 s, 20 s, then 60 s for every further restart', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 9].map(restarts => backoffMs(restarts)), [5_000, 10_000, 20_000, 60_000, 60_000, 60_000]);
});

test('a service nobody runs is started at once; a healthy one is left alone', () => {
  const { actions, state } = run([[none, T0], [up, T0 + 10_000]]);
  assert.deepEqual(actions, ['start', 'none']);
  assert.equal(state.failures, 0);
  assert.equal(state.healthySince, T0 + 10_000);
});

test('three consecutive probe failures of a live process schedule a restart after the backoff', () => {
  const ticks = [[live, T0], [live, T0 + 10_000], [live, T0 + 20_000], [live, T0 + 24_000], [live, T0 + 25_000]];
  const { actions, state } = run(ticks, { ...initialState(), restarts: 0, startedAt: T0 - 120_000 });
  assert.deepEqual(actions, ['none', 'none', 'wait', 'wait', 'restart']);
  assert.equal(state.restarts, 1);
  assert.equal(state.failures, 0);
  assert.equal(state.dueAt, null);
});

test('a dead process is conclusive: no failure count, restart when the backoff elapses', () => {
  const { actions } = run([[dead, T0], [dead, T0 + 4_999], [dead, T0 + 5_000]]);
  assert.deepEqual(actions, ['wait', 'wait', 'restart']);
});

test('one healthy probe resets the failure count but not the restart streak; 60 s healthy resets the streak', () => {
  let { state } = run([[dead, T0], [dead, T0 + 5_000]]);
  assert.equal(state.restarts, 1);
  ({ state } = run([[live, T0 + 70_000], [live, T0 + 80_000], [up, T0 + 90_000]], state));
  assert.equal(state.failures, 0);
  assert.equal(state.restarts, 1, 'streak survives a short healthy spell');
  ({ state } = run([[up, T0 + 150_000]], state));
  assert.equal(state.restarts, 0, 'healthy for healthyResetMs forgets the streak');
});

test('consecutive crashes wait longer each time, capped at 60 s', () => {
  const waits = [];
  let state = initialState();
  let now = T0;
  for (let crash = 0; crash < 5; crash++) {
    const first = decide(state, dead, now);
    state = first.state;
    assert.equal(first.action, 'wait');
    waits.push(state.dueAt - now);
    now = state.dueAt;
    const second = decide(state, dead, now);
    assert.equal(second.action, 'restart');
    state = second.state;
    now += 1_000;
  }
  assert.deepEqual(waits, [5_000, 10_000, 20_000, 60_000, 60_000]);
});

test('probe failures right after a launch are the service booting, not a fault', () => {
  const { actions, state } = run([[none, T0], [live, T0 + 10_000], [live, T0 + 20_000], [live, T0 + 30_000], [live, T0 + 59_000]]);
  assert.deepEqual(actions, ['start', 'none', 'none', 'none', 'none']);
  assert.equal(state.failures, 0, 'nothing counted inside startupGraceMs');
  const after = run([[live, T0 + 61_000], [live, T0 + 71_000], [live, T0 + 81_000]], state);
  assert.deepEqual(after.actions, ['none', 'none', 'wait']);
});

test('short options drive the same rules (what supervise.test.mjs relies on)', () => {
  const options = { ...DEFAULTS, intervalMs: 100, failureThreshold: 2, backoffMs: [50, 100], healthyResetMs: 500, startupGraceMs: 300 };
  const { actions } = run([[none, T0], [up, T0 + 100], [dead, T0 + 200], [dead, T0 + 250], [up, T0 + 400]], initialState(), options);
  assert.deepEqual(actions, ['start', 'none', 'wait', 'restart', 'none']);
});

test('the loop wakes early for a pending restart and otherwise sleeps the interval', () => {
  assert.equal(nextTickMs([initialState()], T0), DEFAULTS.intervalMs);
  assert.equal(nextTickMs([{ ...initialState(), dueAt: T0 + 3_000 }, initialState()], T0), 3_000);
  assert.equal(nextTickMs([{ ...initialState(), dueAt: T0 - 1 }], T0), 0);
});

test('after giveUpAfter restarts without health the policy gives up once and then stays quiet until health returns', () => {
  const options = { ...DEFAULTS, failureThreshold: 1, giveUpAfter: 2, backoffMs: [0] };
  let state = { ...initialState(), restarts: 2, startedAt: 0 };
  const dead = { up: false, known: true, alive: false };
  let next = decide(state, dead, 100_000, options);
  assert.equal(next.action, 'give-up');
  assert.equal(next.state.gaveUp, true);
  next = decide(next.state, dead, 200_000, options);
  assert.equal(next.action, 'none', 'no more launches after giving up');
  next = decide(next.state, { up: true, known: true, alive: true }, 300_000, options);
  assert.equal(next.state.gaveUp, false, 'health (someone restarted it by hand) clears the flag');
  assert.equal(describeState(next.state, { up: true }), 'up');
  assert.equal(describeState({ ...initialState(), gaveUp: true }, { up: false, alive: false }), 'gave_up');
  assert.equal(describeState({ ...initialState(), dueAt: 5 }, { up: false, alive: false }), 'restarting');
  assert.equal(describeState({ ...initialState(), startedAt: 1 }, { up: false, alive: true }), 'starting');
  assert.equal(describeState(initialState(), { up: false, alive: false }), 'down');
});


test('idleStops names up entries whose lease ended idle_timeout_s ago, never within minUpMs of their start, oldest first and capped', () => {
  const options = { ...DEFAULTS, minUpMs: 1_000, maxIdleStopsPerTick: 2 };
  const t0 = Date.parse('2026-10-09T00:00:00Z');
  const entries = [
    { id: 'a', idle_timeout_s: 60 }, { id: 'b', idle_timeout_s: 60 }, { id: 'c', idle_timeout_s: 60 },
    { id: 'd', idle_timeout_s: 60 }, { id: 'keep', idle_timeout_s: null }, { id: 'young', idle_timeout_s: 60 },
  ];
  const iso = ms => new Date(ms).toISOString();
  const records = { a: { startedAt: iso(t0) }, b: { startedAt: iso(t0) }, c: { startedAt: iso(t0) }, d: { startedAt: iso(t0) }, keep: { startedAt: iso(t0) }, young: { startedAt: iso(t0 + 100_000) } };
  const leases = { a: { until: iso(t0 + 10_000) }, b: { until: iso(t0 + 50_000) }, c: { until: iso(t0 + 200_000) } };
  const ups = new Set(['a', 'b', 'c', 'd', 'keep', 'young']);
  // d never leased: idle since start. At t0+100s: a (lease ended 90 s ago), d (100 s) are due; b 50 s ago no; c lease live; young too new.
  assert.deepEqual(idleStops(entries, { ups, leases, records }, t0 + 100_000, options), ['d', 'a']);
  // Cap: at t0+120s a, b, d are due; oldest two.
  assert.deepEqual(idleStops(entries, { ups, leases, records }, t0 + 120_000, options), ['d', 'a']);
  assert.deepEqual(idleStops(entries, { ups, leases, records }, t0 + 120_000, { ...options, maxIdleStopsPerTick: 5 }), ['d', 'a', 'b']);
  assert.deepEqual(idleStops(entries, { ups: new Set(['keep']), leases, records }, t0 + 999_000, options), []);
  assert.equal(idleIn(entries[0], leases.a, records.a, t0, options), 70);
  assert.equal(idleIn(entries[4], null, records.keep, t0, options), null);
});


test('an external (docker compose) entry is never idle-stopped even with a timeout set', () => {
  const t0 = Date.parse('2026-10-09T00:00:00Z');
  const entries = [{ id: 'law', idle_timeout_s: 60, management: 'external' }, { id: 'mass', idle_timeout_s: 60, management: 'agent-host' }];
  const records = { law: { startedAt: new Date(t0).toISOString() }, mass: { startedAt: new Date(t0).toISOString() } };
  assert.deepEqual(idleStops(entries, { ups: new Set(['law', 'mass']), leases: {}, records }, t0 + 10_000_000, { ...DEFAULTS, minUpMs: 0 }), ['mass']);
});
