// Pure decisions for the host supervisor: which registry entries it manages, in what order,
// and when a failing one is restarted. No I/O here; supervise.mjs acts on these answers.

export const DEFAULTS = Object.freeze({
  intervalMs: 10_000,
  failureThreshold: 3,
  backoffMs: Object.freeze([5_000, 10_000, 20_000, 60_000]),
  healthyResetMs: 60_000,
  startupGraceMs: 60_000,
});

/** Entries the host keeps alive by default: persistent editor-owned services; the Orchestrator
 *  and the agents only when asked (their venvs and launcher belong to the Orchestrator session). */
export function defaultSet(services, { withAgents = false } = {}) {
  return services.filter(entry => {
    if (entry.lifecycle !== 'persistent' || !entry.start) return false;
    if (entry.owner_repo === 'editor') return ['editor-session', 'agent-host'].includes(entry.management);
    return withAgents && (entry.kind === 'orchestrator' || entry.kind === 'agent');
  });
}

/** Resolve requested ids against the registry; unknown ids throw, so a typo never starts nothing silently. */
export function selectEntries(services, ids, options) {
  if (!ids.length) return defaultSet(services, options);
  return ids.map(id => {
    const entry = services.find(service => service.id === id);
    if (!entry) throw new Error(`Unknown service "${id}" (not in infra/config/services.json)`);
    if (!entry.start) throw new Error(`Service "${id}" has no start command; nobody starts it from here`);
    return entry;
  });
}

/** Dependencies first (only those inside the set count); a cycle throws. */
export function startOrder(entries) {
  const byId = new Map(entries.map(entry => [entry.id, entry]));
  const ordered = [];
  const marks = new Map();
  const visit = (entry, trail) => {
    const mark = marks.get(entry.id);
    if (mark === 'done') return;
    if (mark === 'active') throw new Error(`depends_on cycle: ${[...trail, entry.id].join(' -> ')}`);
    marks.set(entry.id, 'active');
    for (const dependency of entry.depends_on) {
      if (byId.has(dependency)) visit(byId.get(dependency), [...trail, entry.id]);
    }
    marks.set(entry.id, 'done');
    ordered.push(entry);
  };
  for (const entry of entries) visit(entry, []);
  return ordered;
}

export function initialState() {
  return { failures: 0, restarts: 0, healthySince: null, dueAt: null, startedAt: null };
}

export function backoffMs(restarts, options = DEFAULTS) {
  const steps = options.backoffMs;
  return steps[Math.min(restarts, steps.length - 1)];
}

/**
 * One health observation -> next state and an action.
 *   observation.up     health probe answered 2xx
 *   observation.known  the host has a pid for this service
 *   observation.alive  that pid is a live process
 * Actions: 'none' (healthy or still counting), 'start' (never started: immediately),
 * 'wait' (restart scheduled, not yet due), 'restart' (due now).
 * A dead process is conclusive and skips the failure count; an unanswered probe of a live
 * process must repeat failureThreshold times, and is not counted at all during the
 * startupGraceMs after the host launched it. Delay before the Nth consecutive restart is
 * backoffMs[N-1] (last value repeats); healthyResetMs of health forgets the streak.
 */
export function decide(state, observation, now, options = DEFAULTS) {
  if (observation.up) {
    const healthySince = state.healthySince ?? now;
    const restarts = now - healthySince >= options.healthyResetMs ? 0 : state.restarts;
    return { state: { ...state, failures: 0, restarts, healthySince, dueAt: null }, action: 'none' };
  }
  if (!observation.known && state.restarts === 0) {
    return { state: { ...state, failures: 0, healthySince: null, dueAt: null, startedAt: now }, action: 'start' };
  }
  const dead = observation.known && !observation.alive;
  const booting = !dead && state.startedAt !== null && now - state.startedAt < options.startupGraceMs;
  if (booting) return { state: { ...state, healthySince: null }, action: 'none' };
  const failures = dead ? options.failureThreshold : state.failures + 1;
  if (failures < options.failureThreshold) {
    return { state: { ...state, failures, healthySince: null }, action: 'none' };
  }
  const dueAt = state.dueAt ?? now + backoffMs(state.restarts, options);
  if (now < dueAt) return { state: { ...state, failures, healthySince: null, dueAt }, action: 'wait' };
  return { state: { failures: 0, restarts: state.restarts + 1, healthySince: null, dueAt: null, startedAt: now }, action: 'restart' };
}

/** Milliseconds until the loop should look again: sooner when a restart is pending. */
export function nextTickMs(states, now, options = DEFAULTS) {
  let soonest = options.intervalMs;
  for (const state of states) {
    if (state.dueAt !== null) soonest = Math.min(soonest, Math.max(0, state.dueAt - now));
  }
  return soonest;
}
