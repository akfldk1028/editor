import { expect, test } from 'bun:test'

import type { CollaborationMessage } from './transcript'
import { composeConversation, coveredByLedger, transcriptOf } from './scope'

const message = (over: Partial<CollaborationMessage>): CollaborationMessage =>
  ({ id: 'x', step: 0, direction: 'request', from: 'orchestrator', to: 'law', tool: '', state: 'succeeded', transport: 'a2a', truncated: false, text: '', at: 1_000, ...over })

test('the ledger wins over the live feed for the same words and the same call; what only the feed knows stays, in time order', () => {
  const ledger = [
    message({ id: 'hop:1:request', from: 'user', to: 'orchestrator', text: '조경 의무 면적?', at: 1_000 }),
    message({ id: 'hop:2:request', from: 'orchestrator', to: 'law', text: '{"query": "조경"}', at: 1_200 }),
    message({ id: 'hop:2:response', direction: 'response', from: 'law', to: 'orchestrator', text: '{"total": 1}', at: 3_000 }),
  ]
  const live = [
    message({ id: 'feed:1', from: 'user', to: 'orchestrator', text: '조경 의무 면적?', at: 900 }),
    message({ id: 'feed:2', from: 'orchestrator', to: 'law', text: 'Law Agent에게 묻는 중', at: 1_100, state: 'running' }),
    message({ id: 'feed:3', direction: 'response', from: 'law', to: 'orchestrator', text: '관련 조문 1건', at: 3_100 }),
    message({ id: 'conv:4', direction: 'response', from: 'orchestrator', to: 'user', text: '조경은 건축법 제42조가 정해요.', at: 4_000 }),
    message({ id: 'feed:5', from: 'orchestrator', to: 'law', text: '다른 질문', at: 500_000, state: 'running' }),
  ]
  expect(live.map((item) => coveredByLedger(item, ledger))).toEqual([true, true, true, false, false])
  const composed = composeConversation(ledger, live)
  expect(composed.map((item) => [item.step, item.id])).toEqual([[1, 'hop:1:request'], [2, 'hop:2:request'], [3, 'hop:2:response'], [4, 'conv:4'], [5, 'feed:5']])
  expect(transcriptOf(composed).participants).toEqual(['orchestrator', 'law'])
  expect(transcriptOf([])).toEqual({ participants: [], messages: [], available: true, truncated: false })
})
