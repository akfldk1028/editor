import { expect, test } from 'bun:test'

import { connectionLine, evidenceCard, lawCard, lawLine, requestFailedLine, requestingLines, resultLine, resultPrompt, selectedLine, selectedPrompt, stepChanges, stepState, submittedLine } from './feed-lines'
import { FAST_WINDOW_MS, POLL_FAST_MS, POLL_MS, pollInterval } from './poll'
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

const p1 = { pnu: '4115011300106840001', address: '경기도 의정부시 산곡동 684-1' }
const p2 = { pnu: '4115011300106840003' }

test('the selection line names the site, its parcel count and area', () => {
  expect(selectedLine({ label: '경기도 의정부시 산곡동 684-1', parcels: [p1], total_area_m2: 2499.98 })).toBe('대지 선택: 경기도 의정부시 산곡동 684-1 (1필지, 2,499.98㎡)')
  expect(selectedLine({ label: '산곡동 684-1 외 1', parcels: [p1, p2], total_area_m2: null })).toBe('대지 선택: 산곡동 684-1 외 1 (2필지)')
})

test('after the selection the Orchestrator asks what to do; the user chooses — review is a command, the rest open artifacts', () => {
  const prompt = selectedPrompt({ label: '산곡동 684-1', parcels: [p1], total_area_m2: 2500 })
  expect(prompt.kind).toBe('prompt')
  expect(prompt.agent).toBe('orchestrator')
  expect(prompt.text).toBe('산곡동 684-1 대지가 준비됐어요. 무엇을 할까요?')
  expect(prompt.actions).toEqual([
    { label: '법규·한계 검토 시작', command: { kind: 'start-review', goal: 'limits' } },
    { label: '대지 정보 보기', artifact: 'site-map' },
    { label: '법규 요약 보기', artifact: 'law', params: { pnu: p1.pnu, address: p1.address, tab: 'summary' } },
  ])
  // A parcel without an address falls back to the site label.
  expect(selectedPrompt({ label: '684-3', parcels: [p2], total_area_m2: null }).actions?.[2]?.params).toEqual({ pnu: p2.pnu, address: '684-3', tab: 'summary' })
})

test('the connection line counts agents when up and offers 시스템 보기 when not', () => {
  expect(connectionLine({ state: 'up', agentsUp: 15, agentsTotal: 15 })).toEqual({ kind: 'system', agent: 'orchestrator', text: '오케스트레이터 연결됨 · 에이전트 15/15' })
  const down = connectionLine({ state: 'down', agentsUp: 0, agentsTotal: 15 })
  expect(down.kind).toBe('error')
  expect(down.agent).toBe('orchestrator')
  expect(down.text).toBe('오케스트레이터에 연결할 수 없어요')
  expect(down.actions).toEqual([{ label: '시스템 보기', artifact: 'system' }])
})

test("the click answers at once: the user's bubble with the 조건 and the Orchestrator's busy line; a failure line names 시스템 보기 only when it is off", () => {
  expect(requestingLines('경기도 의정부시 산곡동 684-1', { assessmentDate: '2026-10-08', buildingType: '업무시설' })).toEqual([
    { kind: 'user', text: '검토 시작 · 경기도 의정부시 산곡동 684-1 · 기준일 2026-10-08 · 용도 업무시설' },
    { kind: 'progress', agent: 'orchestrator', tone: 'busy', text: '검토 요청을 전달하는 중' },
  ])
  expect(requestingLines('684-1', { assessmentDate: '2026-10-08', buildingType: ' ' })[0]!.text).toBe('검토 시작 · 684-1 · 기준일 2026-10-08')
  expect(requestFailedLine({ kind: 'unavailable' })).toEqual({
    kind: 'error', agent: 'orchestrator', text: '검토 요청 실패 — 오케스트레이터에 연결할 수 없어요 — 켜진 뒤 다시 시도', actions: [{ label: '시스템 보기', artifact: 'system' }],
  })
  expect(requestFailedLine({ kind: 'rejected', text: '요청이 거절됐어요 (400) — x' })).toEqual({ kind: 'error', agent: 'orchestrator', text: '검토 요청 실패 — 요청이 거절됐어요 (400) — x' })
})

test('polling is fast for the first 20 s of a run, then every 3 s', () => {
  expect(pollInterval(0)).toBe(POLL_FAST_MS)
  expect(pollInterval(FAST_WINDOW_MS - 1)).toBe(POLL_FAST_MS)
  expect(pollInterval(FAST_WINDOW_MS)).toBe(POLL_MS)
  expect([POLL_FAST_MS, POLL_MS]).toEqual([1000, 3000])
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

test('step lines appear once per state change, in Korean, with facts or the failure code and a tone', () => {
  const first = stepChanges(null, { communications: [site, law] })
  expect(first).toEqual([
    { key: 'site_resolve:needs_evidence', text: '대지 사실 확인: 근거 부족 (5/8 사실)', tone: 'warn', agent: 'site_context' },
    { key: 'law_parcel_limits:succeeded', text: '법규 한계: 성공', tone: 'ok', agent: 'law' },
  ])
  expect(stepChanges({ communications: [site, law] }, { communications: [site, law] })).toEqual([])
  expect(stepChanges({ communications: [site, law] }, { communications: [site, law, review] })).toEqual([
    { key: 'revision_triage:needs_evidence', text: '재검토 판정: 근거 부족', tone: 'warn', agent: 'revision' },
  ])
  expect(stepChanges(null, { communications: [apart] })).toEqual([
    { key: 'site_resolve:failed', text: '대지 사실 확인: 실패 — 필지가 서로 붙어 있지 않음', tone: 'warn', agent: 'site_context' },
  ])
  const running = comm('law_parcel_limits', 'law', 'running', null)
  expect(stepChanges({ communications: [running] }, { communications: [law] })).toEqual([{ key: 'law_parcel_limits:succeeded', text: '법규 한계: 성공', tone: 'ok', agent: 'law' }])
  // A step still running has no agent on its record yet: the tool's owner names it.
  expect(stepChanges(null, { communications: [{ ...running, agent: null }] })).toEqual([{ key: 'law_parcel_limits:running', text: '법규 한계: 진행 중', tone: 'busy', agent: 'law' }])
})

test("the law card carries Law's numbers as stat tiles, only the ones it sent", () => {
  expect(lawCard(results())).toEqual({ type: 'stats', items: [
    { label: '대지면적', value: '2,499.7㎡' }, { label: '건폐율', value: '59.92%' }, { label: '용적률', value: '249.67%' }, { label: '최고 층수', value: '5층' },
  ] })
  expect(lawCard(results({ law: { ...results().law!, site_area_m2: null, max_floors: null } }))).toEqual({ type: 'stats', items: [{ label: '건폐율', value: '59.92%' }, { label: '용적률', value: '249.67%' }] })
  expect(lawCard(results({ law: null }))).toBeNull()
})

test('the evidence card lists the missing-evidence codes in Korean, each once, without finding sentences', () => {
  expect(evidenceCard(results())).toEqual({ type: 'chips', items: ['대지 접근(출입구·접도)', '재해 위험 정보', '설비 인입 정보', '기준일 지정', '지구단위계획 시행 근거 미확인'] })
  expect(evidenceCard(results({ missing_evidence_all: ['SITE-ACCESS', 'SITE-ACCESS'] }))).toEqual({ type: 'chips', items: ['대지 접근(출입구·접도)'] })
  expect(evidenceCard(results({ missing_evidence_all: [] }))).toBeNull()
})

test('the prompt asks 법규를 보시겠어요 with 법규 보기 opening the law tab on the site and 나중에 as a plain dismissal', () => {
  const target = { pnu: '4115011300106840001', address: '산곡동 684-1', project: 'p1' }
  const held = resultPrompt(results(), target)
  expect(held.text).toBe('법규 한계는 나왔지만 근거가 더 필요해요. 법규를 보시겠어요?')
  expect(held.actions).toEqual([
    { label: '법규 보기', artifact: 'law', params: { pnu: '4115011300106840001', tab: 'orchestrator', address: '산곡동 684-1', project: 'p1' } },
    { label: '나중에' },
  ])
  expect(resultPrompt(results({ law: null }), target).text).toBe('근거가 부족해 법규 한계를 확정하지 못했어요. 법규를 보시겠어요?')
  expect(resultPrompt(results({ status: 'completed', review: null, missing_evidence_all: [] }), { pnu: 'x' }).text).toBe('법규 검토가 끝났어요. 법규를 보시겠어요?')
  expect(resultPrompt(results({ status: 'completed', review: null, missing_evidence_all: [] }), { pnu: 'x' }).actions[0]).toEqual({ label: '법규 보기', artifact: 'law', params: { pnu: 'x', tab: 'orchestrator' } })
  const failed = resultPrompt(results({ status: 'failed' }), target)
  expect(failed.text).toBe('검토가 실패했어요. 어디서 멈췄는지 법규 패널에서 보시겠어요?')
  expect(failed.actions.map((action) => action.label)).toEqual(['법규 보기', '시스템 보기', '나중에'])
})

test('the law line carries the four numbers as the UI shows them', () => {
  expect(lawLine(results())).toBe('법규 한계: 대지 2,499.7㎡ · 건폐 59.92% · 용적 249.67% · 5층')
  expect(lawLine(results({ law: null }))).toBeNull()
  expect(lawLine(results({ law: { ...results().law!, site_area_m2: null, max_floors: null } }))).toBe('법규 한계: 건폐 59.92% · 용적 249.67%')
})

test('the verdict line says 보류 with the short missing-evidence list, or the failure code', () => {
  expect(resultLine(results())).toBe('검토 결과: 보류 — 근거 보충 필요: 기준일, 대지 접근·재해·설비')
  expect(resultLine(results({ status: 'failed', site: { status: 'failed', code: 'parcels_not_contiguous', facts_known: null, facts_total: null, facts_missing: [] } })))
    .toBe('검토 결과: 실패 — 필지가 서로 붙어 있지 않음')
  expect(resultLine(results({ status: 'completed', review: null, missing_evidence_all: [] }))).toBe('검토 결과: 완료')
})
