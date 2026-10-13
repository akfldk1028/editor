import { expect, test } from 'bun:test'

import { createFeedStore, feed, feedForProject, projectFeed } from './feed'
import { currentConversation, newConversation, selectConversationProject } from '@/lib/design-conversation/session'
import { scopedValue } from '@/lib/design-conversation/useScopedState'


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

test('a tone and a non-empty card are kept; dismiss() drops one line and keeps its key taken', () => {
  const store = createFeedStore()
  const law = store.post({ kind: 'progress', text: '법규', tone: 'ok', card: { type: 'stats', items: [{ label: '건폐율', value: '59.92%' }] } })!
  expect(law.tone).toBe('ok')
  expect(law.card).toEqual({ type: 'stats', items: [{ label: '건폐율', value: '59.92%' }] })
  expect('card' in store.post({ kind: 'result', text: '결과', card: { type: 'chips', items: [] } })!).toBe(false)
  const prompt = store.post({ kind: 'prompt', key: 'r1:prompt', text: '법규를 보시겠어요?', actions: [{ label: '나중에' }] })!
  store.dismiss(prompt.id)
  expect(store.get().map((entry) => entry.kind)).toEqual(['progress', 'result'])
  expect(store.post({ kind: 'prompt', key: 'r1:prompt', text: 'again' })).toBeNull()
  let notified = 0
  store.subscribe(() => notified++)
  store.dismiss(prompt.id)
  expect(notified).toBe(0)
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


test('late run results retain their original project and cannot show actions in another project', () => {
  feed.clear()
  selectConversationProject('a')
  const postA = projectFeed('a')
  selectConversationProject('b')
  postA({ kind: 'result', text: 'A result', actions: [{ label: 'open A', artifact: 'law' }] })
  projectFeed('b')({ kind: 'result', text: 'B result' })
  expect(feedForProject(feed.get(), 'b').map((row) => row.text)).toEqual(['B result'])
  expect(feedForProject(feed.get(), 'a')[0]?.actions?.[0]?.label).toBe('open A')
  selectConversationProject(null)
  feed.clear()
})

test('project and parcel transitions hide the prior run before effects can poll it', () => {
  const run = { run_id: 'a-run' }
  const stored = { scope: JSON.stringify(['a', 'site-1']), value: run }
  expect(scopedValue(stored, JSON.stringify(['b', 'site-1']), null)).toBeNull()
  expect(scopedValue(stored, JSON.stringify(['a', 'site-2']), null)).toBeNull()
  expect(scopedValue(stored, JSON.stringify(['a', 'site-1']), null)).toBe(run)
})

test('a new conversation hides earlier feed actions and late replies in the same project', async () => {
  feed.clear()
  selectConversationProject('same-project')
  const originalId = currentConversation().conversationId
  const originalPost = projectFeed('same-project')
  originalPost({ kind: 'prompt', text: 'original prompt' })
  // No workspace can be made here, so the new conversation stays in the same project.
  const realFetch = globalThis.fetch
  globalThis.fetch = (async () => new Response('{}', { status: 503 })) as unknown as typeof fetch
  await newConversation()
  globalThis.fetch = realFetch
  originalPost({ kind: 'result', text: 'late original result' })
  expect(feedForProject(feed.get(), 'same-project', currentConversation().conversationId)).toEqual([])
  expect(feedForProject(feed.get(), 'same-project', originalId)).toHaveLength(2)
  selectConversationProject(null)
  feed.clear()
})
