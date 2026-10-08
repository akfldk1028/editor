import { expect, test } from 'bun:test'

import { createFeedStore } from './feed'

test('posting appends in order, stamps a time, and notifies subscribers once per post', () => {
  const store = createFeedStore()
  let notified = 0
  const unsubscribe = store.subscribe(() => notified++)
  const first = store.post({ kind: 'system', text: '대지 선택: 684-1 (1필지)', at: 1000 })
  const second = store.post({ kind: 'progress', text: '법규 · 법규 한계: 성공', run_id: 'r1' })
  expect(first?.id).toBe(1)
  expect(second?.id).toBe(2)
  expect(store.get().map((entry) => entry.text)).toEqual(['대지 선택: 684-1 (1필지)', '법규 · 법규 한계: 성공'])
  expect(store.get()[0]!.at).toBe(1000)
  expect(typeof store.get()[1]!.at).toBe('number')
  expect(store.get()[1]!.run_id).toBe('r1')
  expect(notified).toBe(2)
  unsubscribe()
  store.post({ kind: 'error', text: 'x' })
  expect(notified).toBe(2)
})

test('a keyed line posts once; actions are kept only when given', () => {
  const store = createFeedStore()
  expect(store.post({ kind: 'result', key: 'r1:result', text: '검토 결과', actions: [{ label: '법규 결과 보기', artifact: 'law', params: { tab: 'orchestrator' } }] })).not.toBeNull()
  expect(store.post({ kind: 'result', key: 'r1:result', text: '검토 결과 again' })).toBeNull()
  expect(store.get()).toHaveLength(1)
  expect(store.get()[0]!.actions).toEqual([{ label: '법규 결과 보기', artifact: 'law', params: { tab: 'orchestrator' } }])
  expect('actions' in store.post({ kind: 'system', text: 'plain', actions: [] })!).toBe(false)
})

test('the store keeps the newest `limit` lines and clear() empties it and frees keys', () => {
  const store = createFeedStore(3)
  for (let n = 1; n <= 5; n++) store.post({ kind: 'progress', text: `line ${n}` })
  expect(store.get().map((entry) => entry.text)).toEqual(['line 3', 'line 4', 'line 5'])
  store.post({ kind: 'system', key: 'k', text: 'keyed' })
  store.clear()
  expect(store.get()).toEqual([])
  expect(store.post({ kind: 'system', key: 'k', text: 'keyed again' })).not.toBeNull()
})

test('get() returns the same array until something is posted (useSyncExternalStore stability)', () => {
  const store = createFeedStore()
  const before = store.get()
  expect(store.get()).toBe(before)
  store.post({ kind: 'system', text: 'x' })
  expect(store.get()).not.toBe(before)
})
