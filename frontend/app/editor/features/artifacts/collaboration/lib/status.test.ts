import { expect, test } from 'bun:test'

import { runStatusLine, runTone } from './status'
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
