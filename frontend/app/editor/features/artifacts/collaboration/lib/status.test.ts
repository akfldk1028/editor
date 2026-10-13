import { expect, test } from 'bun:test'

import { runStatusLine, runTone, turnSteps, waitingLine } from './status'
import type { CollaborationMessage } from './transcript'

const response = (text: string): CollaborationMessage => ({
  id: 'r', step: 2, direction: 'response', from: 'site_context', to: 'orchestrator', tool: 'site_resolve', state: 'failed', transport: 'a2a', truncated: false, text,
})

test('a failed run says why from the last answer\'s code; a waiting run says what it asks for', () => {
  expect(runStatusLine({ status: 'failed' }, [response('{"status":"failed","code":"site_patch_out_of_scope"}')]))
    .toBe('실패 — Site의 답에 오케스트레이터가 모르는 항목이 있어 답 전체를 받지 않음')
  // The failing step's reason wins over a later held answer (revision asking the person).
  const later = { ...response('{"status":"needs_evidence","code":"needs_user_input"}'), id: 'r2', step: 4, from: 'revision', tool: 'revision_triage', state: 'failed' }
  expect(runStatusLine({ status: 'failed' }, [response('{"code":"site_patch_out_of_scope"}'), later])).toContain('받지 않음')
  // A failing step whose record carries no code (Site's raw answer, cut) is named rather than blamed on a later answer.
  expect(runStatusLine({ status: 'failed' }, [response('{"status": "partial", "summary": "6/9'), later])).toBe('실패 — Site Agent의 대지 사실 확인 단계에서 멈춤 (이유는 기록에 없음)')
  expect(runStatusLine({ status: 'waiting_input', pending_fields: ['building_type'] }, [])).toBe('용도를 묻는 중 — 아직 에이전트를 부르지 않았어요')
  expect(runStatusLine({ status: 'running' }, [])).toBe('진행 중')
  expect(runStatusLine({ status: 'completed' }, [response('{"code":"x"}')])).toBe('완료')
  expect([runTone('running'), runTone('completed'), runTone('failed')]).toEqual(['busy', 'ok', 'warn'])
})

test('the chat says which agent it is waiting on, from the ledger', () => {
  const asked = (to: string, tool: string, state = 'running'): CollaborationMessage => ({ ...response(''), id: `${to}:${tool}`, direction: 'request', from: 'orchestrator', to, tool, state })
  const turn = { ...asked('orchestrator', 'conversation'), from: 'user' }
  expect(waitingLine([turn])).toBe('Orchestrator Agent가 답을 정리하는 중')
  expect(waitingLine([turn, asked('law', 'law_tool_catalog', 'completed'), asked('law', 'law_tool_catalog')])).toBe('Law Agent에게 묻는 중 · 할 수 있는 일 확인')
  // A tool no folder names in words is left out, never shown as its id.
  expect(waitingLine([turn, asked('law', 'law_unnamed_thing')])).toBe('Law Agent에게 묻는 중')
})

test('the chat lists what each agent was asked since the last message, one line per agent', () => {
  const call = (to: string, tool: string, state: string, at: number): CollaborationMessage => ({ ...response(''), id: `${to}:${tool}:${at}`, direction: 'request', from: 'orchestrator', to, tool, state, at })
  const turn = { ...call('orchestrator', 'conversation', 'running', 100), from: 'user' }
  const steps = turnSteps([call('law', 'law_tool_catalog', 'completed', 50), turn, call('law', 'law_tool_catalog', 'completed', 110),
    call('site_context', 'site_unnamed_tool', 'running', 120), call('law', 'law_tool_catalog', 'failed', 130)])
  expect(steps.map(({ label, tools, calls, running, failed }) => [label, tools, calls, running, failed])).toEqual([
    ['Law Agent', ['할 수 있는 일 확인'], 2, false, true],
    ['Site Agent', [], 1, true, false],
  ])
})
