import { expect, test } from 'bun:test'

import type { Hop } from '@/lib/orchestrator-runs/types'

import { fromHops, hopText, scopeQuery } from './hops'

const hop = (over: Partial<Hop>): Hop => ({
  id: 1, trace_id: 'a'.repeat(32), span_id: 'b'.repeat(16), parent_span_id: null, ts_start: '2026-10-12T10:00:00.000Z', ts_end: '2026-10-12T10:00:01.000Z',
  operation: 'invoke_agent', from_agent: 'orchestrator', to_agent: 'law', tool: 'law_search', status: 'OK', error_type: null, state: 'completed', elapsed_ms: 1000,
  conversation_id: 'conv1', run_id: null, task_id: 'task-9', project: null, branch: null, hop: 1, source: 'editor',
  input_messages: [{ role: 'user', parts: [{ type: 'text', content: '{"query": "조경"}' }] }],
  output_messages: [{ role: 'assistant', parts: [{ type: 'text', content: '{"total": 1}' }] }], attrs: {}, recorded_at: '2026-10-12T10:00:01.000Z', ...over,
})

test('a finished call is a request and a response; a running one is a running request; a failed one answers with its error', () => {
  const messages = fromHops([
    hop({ id: 1, from_agent: 'user', to_agent: 'orchestrator', tool: 'ask', input_messages: [{ role: 'user', parts: [{ type: 'text', content: '조경 의무 면적?' }] }], output_messages: null }),
    hop({ id: 2 }),
    hop({ id: 3, ts_end: null, status: 'UNSET', state: 'working', output_messages: null, to_agent: 'site_context' }),
    hop({ id: 4, status: 'ERROR', error_type: 'LawAgentUnavailable', state: 'failed', output_messages: null }),
  ])
  expect(messages.map((m) => [m.step, m.direction, m.from, m.to, m.state, m.a2a_task_id])).toEqual([
    [1, 'request', 'user', 'orchestrator', 'completed', 'task-9'],
    [2, 'request', 'orchestrator', 'law', 'completed', 'task-9'], [3, 'response', 'law', 'orchestrator', 'completed', 'task-9'],
    [4, 'request', 'orchestrator', 'site_context', 'running', 'task-9'],
    [5, 'request', 'orchestrator', 'law', 'failed', 'task-9'], [6, 'response', 'law', 'orchestrator', 'failed', 'task-9'],
  ])
  expect(messages[2]!.text).toBe('{"total": 1}')
  expect(messages[5]!.text).toBe('{"error": "LawAgentUnavailable"}')
  expect(hopText(null)).toBe('')
  expect(scopeQuery({ conversation_id: 'c 1' })).toBe('conversation_id=c%201')
  expect(scopeQuery({ run_id: 'r' })).toBe('run_id=r')
})
