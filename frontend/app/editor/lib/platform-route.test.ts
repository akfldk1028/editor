import { afterEach, expect, spyOn, test } from 'bun:test';
import * as route from '../app/api/v1/platform/[...path]/route';

const originalBackend = process.env.EDITOR_BACKEND_URL;
let fetchSpy: ReturnType<typeof spyOn> | undefined;
afterEach(() => {
  fetchSpy?.mockRestore();
  if (originalBackend === undefined) delete process.env.EDITOR_BACKEND_URL;
  else process.env.EDITOR_BACKEND_URL = originalBackend;
});
const context = (path: string) => ({ params: Promise.resolve({ path: path.split('/') }) });

test('native project context reaches the Editor backend', async () => {
  process.env.EDITOR_BACKEND_URL = 'http://backend.test';
  fetchSpy = spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ scene_revision: 2, source_versions: {} }));
  const response = await route.GET(new Request('http://editor.test/api/v1/platform/projects/p1/context'), context('projects/p1/context'));
  expect(response.status).toBe(200);
  expect(String(fetchSpy.mock.calls[0]![0])).toBe('http://backend.test/api/v1/platform/projects/p1/context');
});

test('native execution submission forwards identity, original origin and body without changing backend status', async () => {
  process.env.EDITOR_BACKEND_URL = 'http://backend.test';
  fetchSpy = spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ run_id: 'r1' }, { status: 202 }));
  const body = JSON.stringify({ request: { goal: 'health' }, scene_revision: 2, source_versions: {} });
  const post = (route as Record<string, Function>).POST;
  expect(typeof post).toBe('function');
  const response = await post!(new Request('http://editor.test/api/v1/platform/projects/p1/runs', {
    method: 'POST', headers: { Origin: 'http://editor.test', 'Idempotency-Key': 'stable-key' }, body,
  }), context('projects/p1/runs'));
  expect(response.status).toBe(202);
  expect(fetchSpy.mock.calls[0]![1]).toMatchObject({ method: 'POST', body,
    headers: { Origin: 'http://editor.test', 'Idempotency-Key': 'stable-key' } });
});

test('cross-origin submission and unknown write paths never reach the backend', async () => {
  process.env.EDITOR_BACKEND_URL = 'http://backend.test';
  fetchSpy = spyOn(globalThis, 'fetch');
  const post = (route as Record<string, Function>).POST;
  expect(typeof post).toBe('function');
  expect((await post!(new Request('http://editor.test/api/v1/platform/projects', { method: 'POST', headers: { Origin: 'http://other.test' } }), context('projects'))).status).toBe(403);
  expect((await post!(new Request('http://editor.test/api/v1/platform/agents', { method: 'POST' }), context('agents'))).status).toBe(404);
  expect(fetchSpy).not.toHaveBeenCalled();
});

test('run results and the newest run per parcel are read-only platform paths the proxy forwards', async () => {
  process.env.EDITOR_BACKEND_URL = 'http://backend.test';
  fetchSpy = spyOn(globalThis, 'fetch').mockImplementation(async () => Response.json({ status: 'blocked' }));
  for (const path of ['runs/8c7f6fb7602f4202ba9537bb94d833b9/results', 'projects/p1/runs/latest']) {
    const response = await route.GET(new Request(`http://editor.test/api/v1/platform/${path}?project_id=p1`), context(path));
    expect(response.status).toBe(200);
  }
  expect(fetchSpy.mock.calls.map((call) => String(call[0]))).toEqual([
    'http://backend.test/api/v1/platform/runs/8c7f6fb7602f4202ba9537bb94d833b9/results?project_id=p1',
    'http://backend.test/api/v1/platform/projects/p1/runs/latest?project_id=p1',
  ]);
  expect((await route.GET(new Request('http://editor.test/api/v1/platform/runs/r1/other'), context('runs/r1/other'))).status).toBe(404);
});
