/**
 * Every backend path the frontend names must (1) pass the matching Next proxy
 * allowlist and (2) exist in backend/route-inventory.json (kept equal to the
 * served routes by backend/tests/test_route_inventory.py). A client that calls a
 * path nobody serves fails here instead of in a user's browser.
 *
 * New client files go in CLIENTS below.
 */
import { afterEach, expect, spyOn, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import * as designRoute from '../app/api/v1/design/[...path]/route';
import * as landRoute from '../app/api/v1/land/[...path]/route';
import * as tilesRoute from '../app/api/v1/land/tiles/[...tile]/route';
import * as lawRoute from '../app/api/v1/law/[...path]/route';
import * as planmRoute from '../app/api/v1/planm/[...path]/route';
import * as platformRoute from '../app/api/v1/platform/[...path]/route';
import * as workspaceRoute from '../app/api/v1/workspace/[...path]/route';

const app = resolve(import.meta.dir, '..');
const inventory = JSON.parse(readFileSync(resolve(app, '../../../backend/route-inventory.json'), 'utf8')) as {
  routes: { method: string; path: string }[];
};

/** `defines` are literals that only build a base other calls extend; they are not requests. */
interface Client { tokens?: Record<string, string>; helpers?: { fn: string; prefix: string }[]; defines?: string[] }
const CLIENTS: Record<string, Client> = {
  'features/design/lib/api-client.ts': { tokens: { '${BASE}': '/api/v1/design', '${AG_LIGHT_BASE}': '/api/v1/design/collaboration' },
    defines: ['/api/v1/design', '/api/v1/design/collaboration'] },
  'features/land/api.ts': { helpers: [{ fn: 'landFetch', prefix: '/api/v1/land' }] },
  'features/land-map/lib/land-api-client.ts': {},
  'features/land-map/lib/constants.ts': {},
  'features/land-map/hooks/use-vworld-3d.ts': {},
  'features/land-map/hooks/use-agent-analyze.ts': {},
  'features/law/lib/law-api-client.ts': { tokens: { '${apiRoot}': '/api/v1' } },
  'features/law/hooks/use-law-search-stream.ts': {},
  'features/agents/api.ts': {},
  'features/agent-dialogue/projects.ts': { helpers: [{ fn: 'request', prefix: '/api/v1/platform/projects' }] },
  'features/agent-dialogue/runs.ts': { helpers: [{ fn: 'request', prefix: '/api/v1/platform' }] },
  'features/agent-dialogue/followup-review.ts': {},
  'features/agent-dialogue/specialist-review.ts': {},
  'features/mcp/api/mcp-client.ts': { tokens: { '${base}': '/api/v1/workspace/mcp/connections' } },
  'features/playground/api/execution-client.ts': { helpers: [{ fn: 'request', prefix: '/api/v1/workspace/runs/${runId}' }],
    defines: ['/api/v1/workspace/runs/${encodeURIComponent(options.runId)}'] },
  'features/gallery/api.ts': { helpers: [{ fn: 'workspaceRequest', prefix: '/api/v1/workspace/' }] },
  'features/sessions/api.ts': { helpers: [{ fn: 'workspaceRequest', prefix: '/api/v1/workspace/' }] },
  'features/team-templates/api.ts': { helpers: [{ fn: 'workspaceRequest', prefix: '/api/v1/workspace/' }] },
};

const BASE_PATH = /\(process\.env\.NEXT_PUBLIC_BASE_PATH \|\| ''\) \+ |\$\{process\.env\.NEXT_PUBLIC_BASE_PATH \|\| ''\}/g;
const SAMPLES = ['1', 'abcdef0123456789abcdef0123456789', '11111111-1111-4111-8111-111111111111', 'abc', 'evidence'];

function rawPaths(file: string, client: Client): string[] {
  let text = readFileSync(resolve(app, file), 'utf8').replace(BASE_PATH, '');
  for (const [token, value] of Object.entries(client.tokens ?? {})) text = text.replaceAll(token, value);
  const found = new Set<string>();
  const skip = new Set([...(client.defines ?? []), ...(client.helpers ?? []).map((h) => h.prefix.replace(/\/$/, ''))]);
  for (const match of text.matchAll(/\/api\/v1\/[^\s'"`]+/g)) if (!skip.has(match[0])) found.add(match[0]);
  for (const { fn, prefix } of client.helpers ?? []) {
    const call = new RegExp(`\\b${fn}(?:<[^(]*?>)?\\(\\s*(['"\`])([^'"\`]*)\\1`, 'g');
    for (const match of text.matchAll(call)) found.add(prefix + match[2]!);
  }
  return [...found];
}

/** Each `${…}` placeholder tried with every sample value: one combination must be served. */
function candidates(raw: string): string[] {
  // `${query}` carries the query string ('' or '?…'), `{z}/{y}/{x}` is a tile template.
  const path = raw.split('?')[0]!.replace(/\$\{query\}/g, '').replace(/\{[xyz]\}/g, '1').replace(/\/$/, '');
  const slots = path.match(/\$\{[^}]*\}/g) ?? [];
  let out = [path];
  for (const slot of slots) out = out.flatMap((p) => SAMPLES.map((s) => p.replace(slot, s)));
  return out;
}

const templates = inventory.routes.map((route) => ({
  ...route,
  pattern: new RegExp('^' + route.path.replace(/[.*+?^$()|[\]\\]/g, '\\$&')
    .replace(/\\?\{([^}]+)\}/g, (_, name: string) => (name.endsWith('path') ? '.+' : '[^/]+')) + '$'),
}));

const PROXIES: Record<string, { module: Record<string, unknown>; param: string }> = {
  design: { module: designRoute, param: 'path' }, land: { module: landRoute, param: 'path' },
  law: { module: lawRoute, param: 'path' }, planm: { module: planmRoute, param: 'path' },
  platform: { module: platformRoute, param: 'path' }, workspace: { module: workspaceRoute, param: 'path' },
};

let fetchSpy: ReturnType<typeof spyOn> | undefined;
const originalBackend = process.env.EDITOR_BACKEND_URL;
afterEach(() => {
  fetchSpy?.mockRestore();
  if (originalBackend === undefined) delete process.env.EDITOR_BACKEND_URL;
  else process.env.EDITOR_BACKEND_URL = originalBackend;
});

async function forwarded(path: string): Promise<boolean> {
  const [, , , domain, ...rest] = path.split('/');
  const tiles = domain === 'land' && rest[0] === 'tiles';
  const proxy = tiles ? { module: tilesRoute as Record<string, unknown>, param: 'tile' } : PROXIES[domain!];
  if (!proxy) return false;
  const segments = tiles ? rest.slice(1) : rest;
  for (const method of ['GET', 'POST', 'PUT', 'DELETE']) {
    const handler = proxy.module[method] as ((r: Request, c: unknown) => Promise<Response>) | undefined;
    if (!handler) continue;
    fetchSpy!.mockClear();
    const response = await handler(
      new Request('http://editor.test' + path, { method, headers: { Origin: 'http://editor.test' } }),
      { params: Promise.resolve({ [proxy.param]: segments }) },
    );
    if (fetchSpy!.mock.calls.length > 0 && ![403, 404, 405].includes(response.status)) return true;
  }
  return false;
}

const served = (path: string) => templates.some((route) => route.pattern.test(path));

for (const [file, client] of Object.entries(CLIENTS)) {
  test(`${file} names only paths the proxies forward and the backend serves`, async () => {
    process.env.EDITOR_BACKEND_URL = 'http://backend.test';
    fetchSpy = spyOn(globalThis, 'fetch').mockImplementation(async () =>
      new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }));
    const raws = rawPaths(file, client);
    expect(raws.length).toBeGreaterThan(0);
    const dead: string[] = [];
    for (const raw of raws) {
      let ok = false;
      for (const candidate of candidates(raw)) {
        if (served(candidate) && (await forwarded(candidate))) { ok = true; break; }
      }
      if (!ok) dead.push(raw);
    }
    expect(dead).toEqual([]);
  });
}
