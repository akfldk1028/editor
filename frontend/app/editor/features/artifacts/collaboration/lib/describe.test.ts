import { expect, test } from 'bun:test'

import { describeMessage } from './describe'
import type { CollaborationMessage } from './transcript'

const message = (over: Partial<CollaborationMessage> = {}): CollaborationMessage => ({
  id: 'c1:request', step: 1, direction: 'request', from: 'orchestrator', to: 'site_context', tool: 'site_resolve', state: 'succeeded',
  transport: 'a2a', truncated: false, text: '{}', ...over,
})

test('a request reads as who asked whom for what, with the arguments in the user\'s words and plumbing hidden', () => {
  const described = describeMessage(message({ text: JSON.stringify({ branch: 'main', project: 'p', parcels: ['1', '2'], pnu: '1168010100107370000', building_type: '업무시설', assessment_date: '2026-10-09' }) }))
  expect(described.headline).toBe('Orchestrator Agent → Site Agent · 대지 사실 확인 요청')
  expect(described.lines).toEqual(['필지 2개', '대지 1168010100107370000', '용도 업무시설', '기준일 2026-10-09'])
  expect(described.raw).not.toContain('"branch"' + ' hidden')
})

test('a response tells the state, the summary, why it ended and which facts were established — never coordinates', () => {
  const body = {
    status: 'failed', code: 'site_patch_out_of_scope', out_of_scope: ['site.zoning'], summary: '6/9 site facts established for 1168010100107370000',
    state_patch: { 'site.boundary': { confidence: 'measured', summary: '면적 13,156.51㎡', value: { geometry: { type: 'Polygon', coordinates: [[[127.03, 37.5]]] } } }, 'site.roads': { summary: '접도 2건 · 폭 15.4m' } },
    facts_missing: ['site.utilities'],
  }
  const described = describeMessage(message({ id: 'c1:response', direction: 'response', from: 'site_context', to: 'orchestrator', state: 'failed', text: JSON.stringify(body) }))
  expect(described.headline).toBe('Site Agent → Orchestrator Agent · 대지 사실 확인 · 실패')
  expect(described.lines).toEqual([
    '6/9 site facts established for 1168010100107370000',
    'Site의 답에 오케스트레이터가 모르는 항목이 있어 답 전체를 받지 않음',
    '오케스트레이터가 받지 않은 항목: 용도지역',
    '확인된 사실 2개: 경계(실측, 면적 13,156.51㎡) · 도로(접도 2건 · 폭 15.4m)',
    '확인 못 한 사실: 설비',
  ])
  expect(described.raw).toContain('[좌표 생략]')
  expect(described.raw).not.toContain('127.03')
})

test('a revision answer lists what it asks the person for and a cut record says so', () => {
  const body = { status: 'needs_evidence', code: 'needs_user_input', actions: [{ finding: 'REQ-INCOMPLETE', recommended_action: 're-run: user', evidence: ['roughly how much floor area?'] }] }
  const described = describeMessage(message({ direction: 'response', from: 'revision', to: 'orchestrator', tool: 'revision_triage', state: 'needs_evidence', text: JSON.stringify(body), truncated: true }))
  expect(described.lines).toEqual(['사용자 입력이 필요함', 'roughly how much floor area? → 사용자 재실행', '기록이 잘렸어요 — 긴 답은 8,000자까지만 남아요'])
  const cut = describeMessage(message({ direction: 'response', from: 'law', to: 'orchestrator', tool: 'law_parcel_limits', text: '{"status":"succeeded","bcr', truncated: true }))
  expect(cut.lines).toEqual(['{"status":"succeeded","bcr … 기록이 잘렸어요'])
  const salvaged = describeMessage(message({ direction: 'response', from: 'site_context', to: 'orchestrator', truncated: true,
    text: '{"status": "partial", "summary": "6/9 site facts established", "state_patch": {"site.boundary": {"confidence": "measured", "value": {"geometry": {"coordinates": [[[127.0' }))
  expect(salvaged.lines).toEqual(['6/9 site facts established', '확인된 사실 1개: 경계(실측) — 잘린 뒤의 사실은 셀 수 없어요', '기록이 잘렸어요 — 긴 답은 8,000자까지만 남아요'])
})

test('the Orchestrator\'s own bookkeeping in a request is counted, not spelled out', () => {
  const described = describeMessage(message({ to: 'revision', tool: 'revision_triage', text: JSON.stringify({ available_owners: ['law'], budget: 3, dirty_nodes: ['requirements.structured_brief'], open_issues: [{ description: 'Floor area is unknown; parking cannot be sized.' }, {}], proposal: {}, rounds_spent: 1 }) }))
  expect(described.lines).toEqual(['열린 이슈: Floor area is unknown; parking cannot be sized.', '열린 이슈 1건', '바뀐 항목: requirements · structured brief', '그 밖의 전달 항목 4개 — 기록 원문에'])
})
