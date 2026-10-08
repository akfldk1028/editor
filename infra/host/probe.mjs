// One HTTP look at a registry entry: is it up, and which version answers.
import { cardUrl, healthUrl } from './registry.mjs';

export const PROBE_TIMEOUT_MS = 3_000;

async function get(url, timeoutMs, fetchImpl) {
  const response = await fetchImpl(url, { headers: { accept: 'application/json' }, signal: AbortSignal.timeout(timeoutMs) });
  let body = null;
  if ((response.headers.get('content-type') ?? '').includes('application/json')) {
    body = await response.json().catch(() => null);
  }
  return { response, body };
}

const pick = (body, keys) => keys.map(key => body?.[key]).find(value => typeof value === 'string' && value !== '');

/**
 * GET the entry's health_url (3 s). `version` comes from the health JSON (`version`, `git_sha`),
 * or from the agent card when version_source says so and health carried none; `startedAt` from
 * `started_at`/`startedAt`. Entries without a health URL (Neo4j) report up: null.
 */
export async function probe(entry, env = process.env, { timeoutMs = PROBE_TIMEOUT_MS, fetchImpl = fetch } = {}) {
  const url = healthUrl(entry, env);
  if (url === null) return { up: null, status: null, latencyMs: 0, error: 'no health URL' };
  const started = performance.now();
  try {
    const { response, body } = await get(url, timeoutMs, fetchImpl);
    const result = {
      up: response.ok,
      status: response.status,
      latencyMs: Math.round(performance.now() - started),
      version: pick(body, ['version', 'git_sha']),
      startedAt: pick(body, ['started_at', 'startedAt']),
    };
    if (result.up && !result.version && entry.version_source === 'card:version' && entry.card_url) {
      result.version = await cardVersion(cardUrl(entry, env), timeoutMs, fetchImpl);
    }
    return result;
  } catch (error) {
    return { up: false, status: null, latencyMs: Math.round(performance.now() - started), error: describe(error) };
  }
}

async function cardVersion(url, timeoutMs, fetchImpl) {
  try {
    const { response, body } = await get(url, timeoutMs, fetchImpl);
    return response.ok ? pick(body, ['version']) : undefined;
  } catch {
    return undefined;
  }
}

function describe(error) {
  const code = [error?.cause?.code, error?.code, error?.name].find(value => typeof value === 'string' && value);
  return code ?? (error instanceof Error ? error.message : String(error));
}
