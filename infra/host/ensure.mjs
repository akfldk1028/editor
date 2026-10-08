// Wait until a set of registry entries answers its health URL — the second half of `ensure`
// (the first half is `start`: wanted + daemon). Pure apart from the injected probe and clock, so
// the CLI and the tests share it. Like KEDA's interceptor, the caller holds its request while
// this waits; unlike a start, an entry that never answers is reported, not retried forever.
import { probe } from './probe.mjs';

export const ENSURE_DEFAULTS = Object.freeze({ timeoutMs: 90_000, intervalMs: 1_000 });

/**
 * Probes every entry in parallel each interval until all are up or the deadline passes.
 * Returns { up: [id], failed: [{ id, error }], waitedMs } — `failed` carries the last probe's error
 * (or `status <code>`), `up` keeps the order of `entries`.
 */
export async function waitHealthy(entries, { timeoutMs = ENSURE_DEFAULTS.timeoutMs, intervalMs = ENSURE_DEFAULTS.intervalMs,
                                             probeImpl = probe, now = Date.now, sleep = ms => new Promise(done => setTimeout(done, ms)) } = {}) {
  const started = now();
  const pending = new Map(entries.map(entry => [entry.id, entry]));
  const last = new Map();
  while (pending.size) {
    const results = await Promise.all([...pending.values()].map(async entry => [entry.id, await probeImpl(entry)]));
    for (const [id, result] of results) {
      last.set(id, result);
      if (result.up === true || result.up === null) pending.delete(id);
    }
    if (!pending.size || now() - started >= timeoutMs) break;
    await sleep(intervalMs);
  }
  const failed = [...pending.keys()].map(id => {
    const result = last.get(id) ?? {};
    return { id, error: result.error ?? (result.status != null ? `status ${result.status}` : 'no answer') };
  });
  return { up: entries.map(entry => entry.id).filter(id => !pending.has(id)), failed, waitedMs: now() - started };
}
