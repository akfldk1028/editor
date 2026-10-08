import { expect, test } from 'bun:test'

import { connectionLine, lawLine, resultLine, selectedLine, stepChanges, stepState, submittedLine } from './feed-lines'
import type { Communication, RunResults } from './types'

const comm = (tool: string, agent: string, state: string, response_text: string | null): Communication => ({
  id: tool, task_id: tool, tool, agent, state, request_text: null, response_text, transport: 'a2a', truncated: false,
})

const site = comm('site_resolve', 'site_context', 'needs_evidence', '{"status": "partial", "summary": "5/8 site facts established for 4115011300106840001", "pnu": "41', )
const law = comm('law_parcel_limits', 'law', 'succeeded', '{"pnu": "4115011300106840001", "parcel_area_m2": 2499.691, "bcr_pct": 59.92')
const review = comm('revision_triage', 'revision', 'failed', '{"status": "needs_evidence", "code": "needs_user_input", "rationale": []}')
const apart = comm('site_resolve', 'site_context', 'failed', '{"status": "failed", "code": "parcels_not_contiguous", "pnu": "x"}')

const results = (over: Partial<RunResults> = {}): RunResults => ({
  run_id: 'r', status: 'blocked', goal: 'limits', pending_input: false, truncated: true,
  request: { pnu: '4115011300106840001', parcels: ['4115011300106840001'], building_type: '업무시설', assessment_date: null },
  steps: [], site: { status: 'partial', code: null, facts_known: 5, facts_total: 8, facts_missing: ['SITE-ACCESS', 'SITE-HAZARDS', 'SITE-UTILITIES'] },
  law: { status: 'succeeded', site_area_m2: 2499.691, bcr_pct: 59.92, far_pct: 249.67, max_floors: 5, policy_id: 'gosan-public1-molit-2026-334',
    parcel_label: null, building_type: '업무시설', ordinance: null, sources: [], findings: [], truncated: true },
  review: { status: 'needs_evidence', code: 'needs_user_input', missing_evidence: ['law.district_review.x: Supply an explicit valid assessment date'], actions: [] },
  missing_evidence_all: ['SITE-ACCESS', 'SITE-HAZARDS', 'SITE-UTILITIES', 'assessment_date_required', 'district_effective_sources_unverified',
    'law.district_review.x: Supply an explicit valid assessment date'],
  notes: [], raw: { communications: 3, keys: {} },
  ...over,
})

test('the selection line names the site, its parcel count and area', () => {
  expect(selectedLine({ label: '경기도 의정부시 산곡동 684-1', parcels: [1], total_area_m2: 2499.98 })).toBe('대지 선택: 경기도 의정부시 산곡동 684-1 (1필지, 2,499.98㎡)')
  expect(selectedLine({ label: '산곡동 684-1 외 1', parcels: [1, 2], total_area_m2: null })).toBe('대지 선택: 산곡동 684-1 외 1 (2필지)')
})

test('the connection line counts agents when up and offers 시스템 보기 when not', () => {
  expect(connectionLine({ state: 'up', agentsUp: 15, agentsTotal: 15 })).toEqual({ kind: 'system', text: '오케스트레이터 연결됨 · 에이전트 15/15' })
  const down = connectionLine({ state: 'down', agentsUp: 0, agentsTotal: 15 })
  expect(down.kind).toBe('error')
  expect(down.text).toBe('오케스트레이터에 연결할 수 없어요')
  expect(down.actions).toEqual([{ label: '시스템 보기', artifact: 'system' }])
})

test('the receipt line shows 8 hex of the run and the trace', () => {
  expect(submittedLine({ run_id: '8c7f6fb7602f4202ba9537bb94d833b9', trace_id: '4bf92f3577b34da6a3ce929d0e0e4736' })).toBe('검토 요청 접수 · run 8c7f6fb7 · trace 4bf92f35')
  expect(submittedLine({ run_id: '8c7f6fb7602f4202ba9537bb94d833b9' })).toBe('검토 요청 접수 · run 8c7f6fb7')
})

test("a step's state prefers the tool's own status word, also inside a cut response", () => {
  expect(stepState(review)).toBe('needs_evidence')
  expect(stepState(apart)).toBe('failed')
  expect(stepState(law)).toBe('succeeded')
  expect(stepState(comm('x', 'law', 'running', null))).toBe('running')
  expect(stepState(comm('x', 'law', 'running', '{"status": "partial"'))).toBe('running')
})

test('step lines appear once per state change, in Korean, with facts or the failure code', () => {
  const first = stepChanges(null, { communications: [site, law] })
  expect(first).toEqual([
    { key: 'site_resolve:needs_evidence', text: '대지 · 대지 사실 확인: 근거 부족 (5/8 사실)' },
    { key: 'law_parcel_limits:succeeded', text: '법규 · 법규 한계: 성공' },
  ])
  expect(stepChanges({ communications: [site, law] }, { communications: [site, law] })).toEqual([])
  expect(stepChanges({ communications: [site, law] }, { communications: [site, law, review] })).toEqual([
    { key: 'revision_triage:needs_evidence', text: '검토 조정 · 재검토 판정: 근거 부족' },
  ])
  expect(stepChanges(null, { communications: [apart] })).toEqual([
    { key: 'site_resolve:failed', text: '대지 · 대지 사실 확인: 실패 — 필지가 서로 붙어 있지 않음' },
  ])
  const running = comm('law_parcel_limits', 'law', 'running', null)
  expect(stepChanges({ communications: [running] }, { communications: [law] })).toEqual([{ key: 'law_parcel_limits:succeeded', text: '법규 · 법규 한계: 성공' }])
  // A step still running has no agent on its record yet: the tool's owner names it.
  expect(stepChanges(null, { communications: [{ ...running, agent: null }] })).toEqual([{ key: 'law_parcel_limits:running', text: '법규 · 법규 한계: 진행 중' }])
})

test('the law line carries the four numbers as the UI shows them', () => {
  expect(lawLine(results())).toBe('법규: 대지 2,499.7㎡ · 건폐 59.92% · 용적 249.67% · 5층')
  expect(lawLine(results({ law: null }))).toBeNull()
  expect(lawLine(results({ law: { ...results().law!, site_area_m2: null, max_floors: null } }))).toBe('법규: 건폐 59.92% · 용적 249.67%')
})

test('the verdict line says 보류 with the short missing-evidence list, or the failure code', () => {
  expect(resultLine(results())).toBe('검토 결과: 보류 — 근거 보충 필요: 기준일, 대지 접근·재해·설비')
  expect(resultLine(results({ status: 'failed', site: { status: 'failed', code: 'parcels_not_contiguous', facts_known: null, facts_total: null, facts_missing: [] } })))
    .toBe('검토 결과: 실패 — 필지가 서로 붙어 있지 않음')
  expect(resultLine(results({ status: 'completed', review: null, missing_evidence_all: [] }))).toBe('검토 결과: 완료')
})
