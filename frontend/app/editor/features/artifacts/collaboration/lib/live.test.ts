import { expect, test } from 'bun:test'

import type { ConversationMessage } from '@/lib/design-conversation/types'
import type { FeedEntry } from '@/lib/orchestrator-runs/feed'

import { liveMessages, waitingOn } from './live'

const entry = (over: Partial<FeedEntry>): FeedEntry => ({ id: 1, kind: 'progress', text: '', at: 1, ...over })

test('a relay is a running request to that agent until the agent speaks; the person and the Orchestrator talk to each other', () => {
  const feed = [
    entry({ id: 1, kind: 'user', text: '조경 의무 면적?', at: 10 }),
    entry({ id: 2, agent: 'orchestrator', tone: 'busy', relay: { from: 'orchestrator', to: 'law' }, text: 'Law Agent에게 묻는 중', at: 11 }),
  ]
  const running = liveMessages(feed, [])
  expect(running.map((m) => [m.step, m.direction, m.from, m.to, m.state])).toEqual([[1, 'request', 'user', 'orchestrator', 'succeeded'], [2, 'request', 'orchestrator', 'law', 'running']])
  expect(waitingOn(running)).toBe('law')
  const answered = liveMessages([...feed, entry({ id: 3, agent: 'law', tone: 'ok', text: "'조경 의무 면적?' 관련 조문 3건", card: { type: 'links', items: [{ label: '건축법 제42조' }] }, at: 12 })], [])
  expect(answered.map((m) => [m.direction, m.from, m.to, m.state])).toEqual([['request', 'user', 'orchestrator', 'succeeded'], ['request', 'orchestrator', 'law', 'succeeded'], ['response', 'law', 'orchestrator', 'succeeded']])
  expect(answered[2]!.text).toBe("'조경 의무 면적?' 관련 조문 3건 — 건축법 제42조")
  expect(waitingOn(answered)).toBeNull()
})

test('the saved conversation adds the owners\' replies in time order and does not repeat a user line the feed already has', () => {
  const saved: ConversationMessage[] = [
    { id: 'u1', role: 'user', agent: null, text: '오피스 지으려고 해요', at: '1970-01-01T00:00:00.005Z' },
    { id: 'a1', role: 'assistant', agent: 'requirement', text: '규모를 알려 주세요', at: '1970-01-01T00:00:00.020Z' },
  ]
  const feed = [entry({ id: 1, kind: 'user', text: '오피스 지으려고 해요', at: 5 }), entry({ id: 2, kind: 'prompt', text: '무시', at: 6 })]
  const merged = liveMessages(feed, saved)
  expect(merged.map((m) => [m.id, m.from, m.to])).toEqual([['feed:1', 'user', 'orchestrator'], ['conv:a1', 'requirement', 'user']])
})
