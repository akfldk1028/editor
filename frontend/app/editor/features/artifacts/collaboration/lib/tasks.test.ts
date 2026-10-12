import { expect, test } from 'bun:test'

import type { AgentTask } from '@/lib/orchestrator-runs/types'

import { fullRecordFor } from './tasks'
import type { CollaborationMessage } from './transcript'

const full = '{"status": "partial", "summary": "6/9", "state_patch": {"site.boundary": {"confidence": "measured"}}}'
const task = (over: Partial<AgentTask>): AgentTask => ({ id: 't', context_id: null, state: 'completed', at: null, tool: 'site_resolve', request_text: '{}', response_text: full, ...over })
const message = (over: Partial<CollaborationMessage>): CollaborationMessage => ({ id: 'c:response', step: 2, direction: 'response', from: 'site_context', to: 'orchestrator', tool: 'site_resolve', state: 'failed', transport: 'a2a', truncated: true, text: full.slice(0, 40), ...over })

test('a cut reply finds the task whose full reply begins with it, preferring the same tool; nothing matches an unrelated or shorter task', () => {
  expect(fullRecordFor(message({}), [task({ id: 'other', tool: 'site_district_plan', response_text: `${full} more` }), task({ id: 'mine' })])?.id).toBe('mine')
  expect(fullRecordFor(message({ text: full, truncated: false }), [task({ id: 'same' })])?.id).toBe('same')
  expect(fullRecordFor(message({}), [task({ response_text: '{"status": "ok"}' })])).toBeNull()
  expect(fullRecordFor(message({ direction: 'request' }), [task({})])).toBeNull()
})
