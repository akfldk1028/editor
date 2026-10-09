import { expect, test } from 'bun:test'
import { discoverOrdinances } from './ordinances'

test('discovery posts the parcel, the date and the cited ordinances, and returns the list as sent', async () => {
  const original = globalThis.fetch
  let sent: { url: string; body: unknown } | null = null
  const answer = {
    pnu: 'p', assessment_date: '2026-10-09', jurisdiction: { address: 'a', status: 'resolved', reason: null, levels: [], notes: [] },
    topics: [], search: { queries: [], complete: true, other_results: 0 }, ordinances: [], excluded: [], coverage_complete: false,
  }
  globalThis.fetch = (async (input, init) => {
    sent = { url: String(input), body: JSON.parse(String(init?.body)) }
    return Response.json(answer)
  }) as typeof fetch
  try {
    const refs = [{ instrument: '을시 도시계획 조례', item_id: 'bcr-cap', article: '제42조' }]
    expect(await discoverOrdinances({ pnu: '1'.repeat(19), assessmentDate: '2026-10-09' }, refs)).toEqual(answer as never)
    expect(sent!.url.endsWith('/api/v1/platform/ordinances')).toBe(true)
    expect(sent!.body).toEqual({ pnu: '1'.repeat(19), assessment_date: '2026-10-09', refs })
    globalThis.fetch = (async () => new Response('x', { status: 503 })) as typeof fetch
    await expect(discoverOrdinances({ pnu: 'p', assessmentDate: '2026-10-09' }, [])).rejects.toThrow('조례가 없다는 뜻은 아닙니다')
    globalThis.fetch = (async () => Response.json({ nope: true })) as typeof fetch
    await expect(discoverOrdinances({ pnu: 'p', assessmentDate: '2026-10-09' }, [])).rejects.toThrow('형식')
  } finally { globalThis.fetch = original }
})
