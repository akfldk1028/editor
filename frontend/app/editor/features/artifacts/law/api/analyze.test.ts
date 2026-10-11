import { expect, test } from 'bun:test'
import { analyzeSite } from './analyze'

test('analysis waits for Law activation, preserves input, and stops on activation failure', async () => {
  const original = globalThis.fetch
  const calls: { url: string; body: unknown }[] = []
  let failed = false
  globalThis.fetch = (async (url, init) => {
    calls.push({ url: String(url), body: JSON.parse(String(init?.body)) })
    return Response.json(String(url).endsWith('/ensure')
      ? { up: failed ? [] : ['law'], failed: failed ? [{ agent: 'law', error: 'offline' }] : [] }
      : { pnu: 'parcel' })
  }) as typeof fetch
  try {
    await analyzeSite('parcel', { assessmentDate: '2026-10-09' })
    expect(calls.map(call => call.url)).toEqual(['/api/v1/platform/host/ensure', '/api/v1/platform/law-analysis'])
    expect(calls[1]?.body).toEqual({ pnu: 'parcel', assessment_date: '2026-10-09' })
    failed = true
    calls.length = 0
    await expect(analyzeSite('parcel', {})).rejects.toThrow('시작하지 못했어요')
    expect(calls).toHaveLength(1)
  } finally { globalThis.fetch = original }
})
