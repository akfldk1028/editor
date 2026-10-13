import { expect, test } from 'bun:test'

import { turnSteps, waitingLine } from './steps'
import type { LedgerMessage } from './types'

const response = (text: string): LedgerMessage => ({
  id: 'r', step: 2, direction: 'response', from: 'site_context', to: 'orchestrator', tool: 'site_resolve', state: 'failed', transport: 'a2a', truncated: false, text,
})

test('the chat says which agent it is waiting on, from the ledger', () => {
  const asked = (to: string, tool: string, state = 'running'): LedgerMessage => ({ ...response(''), id: `${to}:${tool}`, direction: 'request', from: 'orchestrator', to, tool, state })
  const turn = { ...asked('orchestrator', 'conversation'), from: 'user' }
  expect(waitingLine([turn])).toBe('Orchestrator Agent가 답을 정리하는 중')
  expect(waitingLine([turn, asked('law', 'law_tool_catalog', 'completed'), asked('law', 'law_tool_catalog')])).toBe('Law Agent에게 묻는 중 · 할 수 있는 일 확인')
  // A tool no folder names in words is left out, never shown as its id.
  expect(waitingLine([turn, asked('law', 'law_unnamed_thing')])).toBe('Law Agent에게 묻는 중')
})

test('the chat lists what each agent was asked since the last message, one line per agent', () => {
  const call = (to: string, tool: string, state: string, at: number): LedgerMessage => ({ ...response(''), id: `${to}:${tool}:${at}`, direction: 'request', from: 'orchestrator', to, tool, state, at })
  const turn = { ...call('orchestrator', 'conversation', 'running', 100), from: 'user' }
  const steps = turnSteps([call('law', 'law_tool_catalog', 'completed', 50), turn, call('law', 'law_tool_catalog', 'completed', 110),
    call('site_context', 'site_unnamed_tool', 'running', 120), call('law', 'law_tool_catalog', 'failed', 130)])
  expect(steps.map(({ label, tools, calls, running, failed }) => [label, tools, calls, running, failed])).toEqual([
    ['Law Agent', ['할 수 있는 일 확인'], 2, false, true],
    ['Site Agent', [], 1, true, false],
  ])
})
