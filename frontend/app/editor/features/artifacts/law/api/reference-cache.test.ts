import { expect, test } from 'bun:test'
import { createReferenceCache } from './reference-cache'
import type { ReviewRef } from '../lib/review'

const ref: ReviewRef = { instrument: '갑시 조례', kind: 'ordinance', article: '제1조', clause: null, text: null, text_status: 'needs_source' }
const site = { pnu: 'site', assessmentDate: '2026-10-09' }

test('source cache shares in-flight work, expires, refreshes and separates date/edition', async () => {
  let calls = 0
  let now = 0
  const load = createReferenceCache(async () => { calls++; return { text: '원문' } }, () => now)
  await Promise.all([load(ref, site), load(ref, site)])
  await load(ref, site)
  expect(calls).toBe(1)
  await load(ref, { ...site, assessmentDate: '2025-01-01' })
  await load({ ...ref, edition_id: 'another' }, site)
  expect(calls).toBe(3)
  await load(ref, site, true)
  expect(calls).toBe(4)
  now = 300_001
  await load(ref, site)
  expect(calls).toBe(5)
})

test('source failures are not cached', async () => {
  let calls = 0
  const load = createReferenceCache(async () => { if (++calls === 1) throw new Error('offline'); return { text: '원문' } })
  await expect(load(ref, site)).rejects.toThrow('offline')
  expect((await load(ref, site)).text).toBe('원문')
  expect(calls).toBe(2)
})
