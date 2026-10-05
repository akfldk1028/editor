import { afterEach, expect, test } from 'bun:test';
import { createMaasAesthetic, getDesignDetail, getDesignEvidence } from './api-client';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test('detail/evidence preserve exact encoded UID and numeric-only URLs', async () => {
  const urls: string[] = [];
  globalThis.fetch = (async (url: string | URL | Request) => {
    urls.push(String(url));
    return new Response('{}');
  }) as typeof fetch;
  const uid = 'old algorithm:7/a?b&c';
  await getDesignDetail('job', 7, uid);
  await getDesignEvidence('job', 7, uid);
  expect(urls.map(url => new URL(url,'http://test').searchParams.get('design_uid'))).toEqual([uid,uid]);
  expect(new URL(urls[0]!, 'http://test').pathname).toBe('/api/v1/design/jobs/job/results/7/');
  expect(new URL(urls[1]!, 'http://test').pathname).toBe('/api/v1/design/jobs/job/results/7/evidence/');
  await getDesignEvidence('job', 7);
  expect(urls[2]).toBe('/api/v1/design/jobs/job/results/7/evidence/');
  await getDesignEvidence('job', 7, '');
  expect(urls[3]).toEndWith('?design_uid=');
});

test('aesthetic sends selected UID alongside provider and keeps cancellation signal', async () => {
  const controller = new AbortController();
  let captured: RequestInit | undefined;
  globalThis.fetch = (async (_url: unknown, init?: RequestInit) => {
    captured = init;
    return new Response('{}');
  }) as typeof fetch;
  await createMaasAesthetic({job_id:'job',design_id:0,design_uid:'additive:0',provider:'placeholder'}, controller.signal);
  expect(JSON.parse(String(captured?.body))).toMatchObject({design_uid:'additive:0',provider:'placeholder'});
  expect(captured?.signal).toBe(controller.signal);
});

test('unknown UID and numeric ambiguity errors are not retried without UID', async () => {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return new Response(JSON.stringify({error:'Design not found for requested identity'}), {status:404});
  }) as typeof fetch;
  await expect(getDesignEvidence('job',7,'wrong')).rejects.toThrow('requested identity');
  expect(calls).toBe(1);
});
