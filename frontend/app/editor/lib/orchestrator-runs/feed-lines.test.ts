import { expect, test } from 'bun:test'

import {
  activatingLine, activationFailedLine, answerLine, askFailedLine, askLines, connectionLine, evidenceCard, landAnalysisLine, landAnalysisLines, lawBasisLine, lawCard, lawLine, relayLine, requestFailedLine,
  siteLocateParams, siteLocatedLine,
  requestingLines, resultLine, resultPrompt, revisionLine, selectedLine, selectedPrompt, siteFactsLine, stepChanges, stepState, submittedLine,
} from './feed-lines'
import { FALLBACK } from '@/lib/goals'

import type { AskAnswer, LandAnalysisAnswer } from './types'
import { FAST_WINDOW_MS, POLL_FAST_MS, POLL_MS, pollInterval } from './poll'
import type { Communication, RunResults } from './types'

const comm = (tool: string, agent: string, state: string, response_text: string | null): Communication => ({
  id: tool, task_id: tool, tool, agent, state, request_text: null, response_text, transport: 'a2a', truncated: false,
})

const site = comm('site_resolve', 'site_context', 'needs_evidence', '{"status": "partial", "summary": "5/8 site facts established for 4115011300106840001", "pnu": "41', )
const law = comm('law_parcel_limits', 'law', 'succeeded', '{"pnu": "4115011300106840001", "parcel_area_m2": 2499.691, "bcr_pct": 59.92')
const review = comm('revision_triage', 'revision', 'failed', '{"status": "needs_evidence", "code": "needs_user_input", "rationale": []}')
const apart = comm('site_resolve', 'site_context', 'failed', '{"status": "failed", "code": "parcels_not_contiguous", "pnu": "x"}')

const siteFacts = [
  { key: 'site.boundary', confidence: 'measured', source: 'Vworld 연속지적도', as_of: '2026-10-08', summary: '면적 2,499.69㎡' },
  { key: 'site.roads', confidence: 'measured', source: 'NGII', as_of: '2026-10-08', summary: '접도 5건 · 폭 15m, 20m' },
]
const noEvidence = { floor_height_m: null, datum_measured: null, frontage_grade: null, legal_floor_section_count: null }

const results = (over: Partial<RunResults> = {}): RunResults => ({
  run_id: 'r', status: 'blocked', goal: 'limits', pending_input: false, truncated: true,
  request: { pnu: '4115011300106840001', parcels: ['4115011300106840001'], building_type: '업무시설', assessment_date: null },
  steps: [], site: { status: 'partial', code: null, facts_known: 5, facts_total: 8, facts_missing: ['SITE-ACCESS', 'SITE-HAZARDS', 'SITE-UTILITIES'], facts: siteFacts },
  law: { status: 'succeeded', site_area_m2: 2499.691, bcr_pct: 59.92, far_pct: 249.67, max_floors: 5, ground_capacity_m2: null, far_capacity_m2: null, zones: [],
    national_bcr_ceiling_pct: null, national_far_ceiling_pct: null, articles: { bcr: null, far: null, height: null }, height: { status: null, limit_m: null },
    policy_id: 'gosan-public1-molit-2026-334', parcel_label: null, building_type: '업무시설', ordinance: null, evidence: noEvidence, sources: [], findings: [], truncated: true },
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
  const prompt = selectedPrompt({ label: '산곡동 684-1', parcels: [p1], total_area_m2: 2500 }, FALLBACK)
  expect(prompt.kind).toBe('prompt')
  expect(prompt.agent).toBe('orchestrator')
  expect(prompt.text).toBe('산곡동 684-1 — 무엇을 할까요?')
  expect(prompt.actions).toEqual([
    { label: '설계 시작하기', command: { kind: 'compose', draft: '이 대지에서 설계를 시작하고 싶어요.' } },
    { label: '법규 검토', artifact: 'law', params: { pnu: p1.pnu, address: p1.address, parcelCount: '1', tab: 'review' } },
  ])
  // Quick actions retain the catalog's availability, offer flag, and presentation label.
  const wider = { ...FALLBACK, goals: [...FALLBACK.goals, { id: 'mass', label: '매스 생성', owners: ['mass'], inputs: [], optional: [], available: true, offer: true },
    { id: 'elevation', label: '입면 설계', owners: ['elevation'], inputs: [], optional: [], available: false, offer: true }], conversation: { ask: true, law_analysis: false } }
  expect(selectedPrompt({ label: '684-3', parcels: [p2], total_area_m2: null }, wider).actions?.map((action) => action.label)).toEqual(['설계 시작하기', '법규 검토', '매스 생성'])
})

test('the connection line counts agents when up and offers 시스템 보기 when not', () => {
  expect(connectionLine({ state: 'up', agentsUp: 15, agentsTotal: 15 })).toEqual({ kind: 'system', agent: 'orchestrator', text: 'Orchestrator Agent 연결됨 · 에이전트 15/15' })
  const down = connectionLine({ state: 'down', agentsUp: 0, agentsTotal: 15 })
  expect(down.kind).toBe('error')
  expect(down.agent).toBe('orchestrator')
  expect(down.text).toBe('Orchestrator Agent에 연결할 수 없어요')
  expect(down.actions).toEqual([{ label: '시스템 보기', artifact: 'system' }])
})

test("the click answers at once: the user's bubble with the 조건 and the Orchestrator's busy line; a failure line names 시스템 보기 only when it is off", () => {
  expect(requestingLines('경기도 의정부시 산곡동 684-1', { assessmentDate: '2026-10-08', buildingType: '업무시설' })).toEqual([
    { kind: 'user', text: '검토 시작 · 경기도 의정부시 산곡동 684-1 · 기준일 2026-10-08 · 용도 업무시설' },
    { kind: 'progress', agent: 'orchestrator', tone: 'busy', relay: { from: 'user', to: 'orchestrator' }, text: 'Orchestrator Agent에게 검토 요청 중' },
  ])
  expect(requestingLines('684-1', { assessmentDate: '2026-10-08', buildingType: ' ' })[0]!.text).toBe('검토 시작 · 684-1 · 기준일 2026-10-08')
  expect(requestFailedLine({ kind: 'unavailable' })).toEqual({
    kind: 'error', agent: 'orchestrator', text: '검토 요청 실패 — Orchestrator Agent에 연결할 수 없어요 — 켜진 뒤 다시 시도', actions: [{ label: '시스템 보기', artifact: 'system' }],
  })
  expect(requestFailedLine({ kind: 'rejected', text: '요청이 거절됐어요 (400) — x' })).toEqual({ kind: 'error', agent: 'orchestrator', text: '검토 요청 실패 — 요청이 거절됐어요 (400) — x' })
})

test('polling is fast for the first 20 s of a run, then every 3 s', () => {
  expect(pollInterval(0)).toBe(POLL_FAST_MS)
  expect(pollInterval(FAST_WINDOW_MS - 1)).toBe(POLL_FAST_MS)
  expect(pollInterval(FAST_WINDOW_MS)).toBe(POLL_MS)
  expect([POLL_FAST_MS, POLL_MS]).toEqual([1000, 3000])
})

test("a typed question: the user's bubble and the Orchestrator asking the Law Agent; the answer is the Law Agent's turn with links", () => {
  expect(askLines('자연녹지지역 건폐율')).toEqual([{ kind: 'user', text: '자연녹지지역 건폐율' }, { kind: 'progress', agent: 'orchestrator', tone: 'busy', relay: { from: 'user', to: 'orchestrator' }, text: 'Orchestrator Agent가 담당을 고르는 중' }])
  expect(askLines('자연녹지지역 건폐율', 'law')).toEqual([{ kind: 'user', text: 'Law Agent에게: 자연녹지지역 건폐율' }, { kind: 'progress', agent: 'orchestrator', tone: 'busy', relay: { from: 'orchestrator', to: 'law' }, text: 'Law Agent에게 묻는 중' }])
  const evidence = { assessment_date: '2026-10-08', currency_status: 'needs_evidence', coverage_status: 'needs_evidence', reason: 'r' }
  const skill = (agent: string, skill: string) => ({ kind: 'skill' as const, agent, skill, goal: null, confidence: 0.7, reason: 'r', choices: [] })
  const search: AskAnswer = {
    question: '자연녹지지역 건폐율', tool: 'law_search', agent: 'law', trace_id: 't', version: 'v', route: skill('law', 'law_search'), handoff: null,
    answer: { kind: 'search', total: 5, degraded: false, legal_evidence: evidence, items: [
      { id: 'a', law: '국토의 계획 및 이용에 관한 법률', kind: '시행령', article: '제84조', text: '제1항에도 불구하고 …' },
      { id: 'b', law: '건축법', kind: '법률', article: '제55조', text: null },
    ] },
  }
  const target = { pnu: '4115011300106830000', address: '산곡동 683' }
  const line = answerLine(search, target)
  expect(line.agent).toBe('law')
  expect(line.text).toBe("'자연녹지지역 건폐율' 관련 조문 5건 — 국토의 계획 및 이용에 관한 법률, 건축법 · 기준일 2026-10-08 · 최신성·적용 범위는 확인 필요")
  expect(line.card).toEqual({ type: 'links', items: [
    { label: '국토의 계획 및 이용에 관한 법률 (시행령) 제84조', note: '제1항에도 불구하고 …' }, { label: '건축법 (법률) 제55조' },
  ] })
  expect(line.actions).toEqual([{ label: '관련 법규 보기', artifact: 'law', params: { pnu: target.pnu, tab: 'articles', address: '산곡동 683' } }])
  expect(answerLine({ ...search, answer: { ...search.answer, items: [], total: 0 } }, null)).toEqual({ kind: 'progress', agent: 'law', tone: 'warn', text: "'자연녹지지역 건폐율' 관련 조문을 찾지 못했어요", actions: [] })

  const ordinance: AskAnswer = {
    question: '의정부시 도시계획 조례 제42조', tool: 'law_ordinance', agent: 'law', trace_id: 't', version: null, route: skill('law', 'law_ordinance'), handoff: null,
    answer: { kind: 'ordinance', legal_evidence: evidence,
      ordinance: { name: '의정부시 도시계획 조례', ordinance_id: '2149163', edition_id: '2072835', effective_date: '2025-09-25', url: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2072835' },
      matches: [{ article: '제42조', title: '용도지역안에서의 건폐율', text: '제42조(용도지역안에서의 건폐율) …' }] },
  }
  const ord = answerLine(ordinance, null)
  expect(ord.text).toBe('의정부시 도시계획 조례 제42조 (용도지역안에서의 건폐율) · 기준일 2026-10-08 · 최신성·적용 범위는 확인 필요')
  expect(ord.card).toEqual({ type: 'links', items: [
    { label: '의정부시 도시계획 조례 — law.go.kr', href: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2072835', note: '판본 2072835 · 시행 2025-09-25' },
    { label: '제42조 용도지역안에서의 건폐율', note: '제42조(용도지역안에서의 건폐율) …' },
  ] })
  // A goal handoff: open → offer to start it; closed → say so. Unsure → the roles as choices that re-ask with that role.
  const handoff = (available: boolean): AskAnswer => ({ question: '매스 쌓아 봐', agent: 'mass', tool: null, trace_id: null, version: null, answer: null,
    route: { kind: 'goal', agent: 'mass', skill: null, goal: 'mass', confidence: 0.7, reason: 'r', choices: [] },
    handoff: { goal: 'mass', label: '매스 생성', owners: ['program', 'masterplan', 'mass', 'revision'], available } })
  expect(answerLine(handoff(true), null)).toEqual({ kind: 'prompt', agent: 'orchestrator', text: '이건 Mass Agent의 일이에요 — 매스 생성을(를) 시작할까요?',
    actions: [{ label: '매스 생성 시작', command: { kind: 'start-review', goal: 'mass' } }, { label: '나중에' }] })
  expect(answerLine(handoff(false), null).text).toBe('이건 Mass Agent의 일이에요 (매스 생성: Program Agent → MasterPlan Agent → Mass Agent → Revision Agent) — 이 목표는 아직 열리지 않았어요')
  const unsure: AskAnswer = { question: '뭐 할 수 있어?', agent: null, tool: null, trace_id: null, version: null, answer: null, handoff: null,
    route: { kind: 'ask', agent: null, skill: null, goal: null, confidence: 0.3, reason: '어느 에이전트의 일인지 분명하지 않아요', choices: [{ agent: 'law', label: '법령·조례 검색 (Law Agent)' }, { agent: 'mass', label: '매스 생성 (Mass Agent)' }] } }
  expect(answerLine(unsure, null)).toEqual({ kind: 'prompt', agent: 'orchestrator', text: '어느 에이전트의 일인지 분명하지 않아요. 누구에게 물을까요?',
    actions: [{ label: '법령·조례 검색 (Law Agent)', command: { kind: 'ask', text: '뭐 할 수 있어?', role: 'law' } }, { label: '매스 생성 (Mass Agent)', command: { kind: 'ask', text: '뭐 할 수 있어?', role: 'mass' } }, { label: '나중에' }] })
  const replied: AskAnswer = { ...unsure, question: '안녕, 뭐 할 수 있어?', route: { kind: 'answer', agent: 'orchestrator', skill: null, goal: null, confidence: 0.85, reason: '소개는 제가 답해요', choices: [], decided_by: 'llm', instruction: '안녕하세요! 지금은 법규·한계 검토가 열려 있어요.' } }
  expect(answerLine(replied, null)).toEqual({ kind: 'progress', agent: 'orchestrator', tone: 'ok', text: '안녕하세요! 지금은 법규·한계 검토가 열려 있어요.' })
  const told: AskAnswer = { ...handoff(false), route: { ...handoff(false).route, decided_by: 'llm', instruction: '이 대지에 매스를 쌓아 주세요' } }
  expect(answerLine(told, null).text).toContain('Mass Agent에게: "이 대지에 매스를 쌓아 주세요"')
  expect(askFailedLine(503, null)).toEqual({ kind: 'error', agent: 'orchestrator', text: 'Law Agent에 연결할 수 없어요 — 켜진 뒤 다시 물어보세요', actions: [{ label: '시스템 보기', artifact: 'system' }] })
  expect(askFailedLine(502, 'law_agent_error: law_search: TASK_STATE_FAILED')).toEqual({ kind: 'error', agent: 'orchestrator', text: 'Law Agent가 답하지 못했어요 — law_agent_error: law_search: TASK_STATE_FAILED' })
})

test("a land analysis: the user's 법규 요약 bubble, the Orchestrator asking, then the Law Agent's caps, zones, restrictions and what is missing", () => {
  expect(landAnalysisLines('산곡동 684-1', { buildingType: '업무시설', assessmentDate: '2026-10-08' })).toEqual([
    { kind: 'user', text: '법규 요약 · 산곡동 684-1 · 기준일 2026-10-08 · 용도 업무시설' },
    { kind: 'progress', agent: 'orchestrator', tone: 'busy', relay: { from: 'orchestrator', to: 'law' }, text: 'Law Agent에게 법규 분석 요청 중' },
  ])
  const target = { pnu: '4115011300106840001', address: '산곡동 684-1' }
  const answer: LandAnalysisAnswer = {
    pnu: target.pnu, agent: 'law', trace_id: 't', version: 'v', limits_error: null,
    limits: { ...results().law!, policy_id: 'gosan-public1-molit-2026-334', articles: { bcr: '의정부시 도시계획 조례 제42조', far: '의정부시 도시계획 조례 제46조', height: null } },
    summary: { zones: ['제2종일반주거지역', '자연녹지지역'], unmatched_zones: ['공공청사'], zone_areas_m2: { 제2종일반주거지역: 2499.69, 자연녹지지역: 4.85 },
      restrictions: ['a', 'b', 'c'], assessment_status: 'needs_evidence', permit_compliance_verified: false,
      missing_evidence: ['complete_design_applicability_and_permit_checks', 'unresolved_zoning:공공청사'] },
  }
  const line = landAnalysisLine(answer, target)
  expect(line.agent).toBe('law')
  expect(line.tone).toBe('warn')
  // The user's words only — no policy id, no tool name; what still needs checking on its own line.
  expect(line.text).toContain('법규 요약 (제2종일반주거지역 · 자연녹지지역): 건폐율 59.92% · 용적률 249.67% · 최고 5층 · 제한 3건\n확인 필요: 설계 적용성·허가 검토 미완료, 용도 구분 미확인: 공공청사')
  expect(line.text).not.toContain('gosan-public1')
  // A hair of another zone the split excluded is disclosed next to the caps, in the words the backend wrote.
  const note = '자연녹지지역: 토지이용계획 속성에는 표시되나 측정 폭 0.09 m, 4.85㎡(0.19%)의 용도지역 폴리곤끼리 겹친 부분으로 제84조 분할에서 제외, 제2종일반주거지역에 귀속'
  const disclosed = landAnalysisLine({ ...answer, limits: { ...answer.limits!, zone_split: { areas_m2: { 제2종일반주거지역: 2499.69 }, excluded_slivers: [{ zone: '자연녹지지역', area_m2: 4.85, width_m: 0.089, share: 0.00194, reason: 'zone_overlap', folded_into: '제2종일반주거지역' }], uncovered_m2: 0, notes: [note], removed_zones: ['자연녹지지역'] } } }, target)
  expect(disclosed.text).toContain(`\n${note}\n\n이 대지에`)
  expect((line.card as { items: { label: string; value: string }[] }).items[1]).toEqual({ label: '건폐율', value: '59.92%', hint: '의정부시 도시계획 조례 제42조' })
  expect(line.actions?.map((action) => `${action.label}→${action.params?.tab}`)).toEqual(['검토 조항 보기→review', '설계 방향 이야기하기→undefined'])
  const noLimits = landAnalysisLine({ ...answer, limits: null, limits_error: 'LawAgentError: x' }, target)
  expect(noLimits.text).toContain('상한 미확정')
  expect(noLimits.text).not.toContain('law_parcel_limits')
  expect(noLimits.card).toBeUndefined()
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
    { key: 'site_resolve:needs_evidence', tool: 'site_resolve', text: '대지 사실 확인: 근거 부족 (5/8 사실)', tone: 'warn', agent: 'site_context' },
    { key: 'law_parcel_limits:succeeded', tool: 'law_parcel_limits', text: '법규 한계: 성공', tone: 'ok', agent: 'law' },
  ])
  expect(stepChanges({ communications: [site, law] }, { communications: [site, law] })).toEqual([])
  expect(stepChanges({ communications: [site, law] }, { communications: [site, law, review] })).toEqual([
    { key: 'revision_triage:needs_evidence', tool: 'revision_triage', text: '재검토 판정: 근거 부족', tone: 'warn', agent: 'revision' },
  ])
  expect(stepChanges(null, { communications: [apart] })).toEqual([
    { key: 'site_resolve:failed', tool: 'site_resolve', text: '대지 사실 확인: 실패 — 필지가 서로 붙어 있지 않음', tone: 'warn', agent: 'site_context' },
  ])
  const running = comm('law_parcel_limits', 'law', 'running', null)
  expect(stepChanges({ communications: [running] }, { communications: [law] })).toEqual([{ key: 'law_parcel_limits:succeeded', tool: 'law_parcel_limits', text: '법규 한계: 성공', tone: 'ok', agent: 'law' }])
  // A step still running has no agent on its record yet: the tool's owner names it.
  const started = stepChanges(null, { communications: [{ ...running, agent: null }] })
  expect(started).toEqual([{ key: 'law_parcel_limits:running', tool: 'law_parcel_limits', text: '법규 한계: 진행 중', tone: 'busy', agent: 'law' }])
  // While it runs, the Orchestrator says whom it is asking.
  expect(relayLine(started[0]!)).toEqual({ kind: 'progress', agent: 'orchestrator', tone: 'busy', relay: { from: 'orchestrator', to: 'law' }, text: 'Law Agent에게 법규 한계 요청 중' })
})

test("Law's legal basis: the ordinance source with its law.go.kr link, the articles, limitations and Law's premises; the truncation is named", () => {
  const target = { pnu: '4115011300106830000', address: '산곡동 683', project: 'p1' }
  const related = { label: '관련 법규 보기', artifact: 'law', params: { pnu: target.pnu, tab: 'articles', address: '산곡동 683', project: 'p1' } }
  const receipt = {
    articles: ['의정부시 도시계획 조례 제42조', '의정부시 도시계획 조례 제46조', '건축법 제60조, 국토계획법 시행령 제80조'], edition_id: '2072835', effective_date: '20250925', assessment_date: '2026-10-08',
    sources: [{ name: '의정부시 도시계획 조례', ordinance_id: '2149163', edition_id: '2072835', effective_date: '20250925', url: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2072835' }],
    limitations: ['snapshot_does_not_certify_amendment_completeness'],
  }
  const evidence = { floor_height_m: 3.8, datum_measured: false, frontage_grade: 'inferred_not_road_verified', legal_floor_section_count: 13 }
  const withReceipt = lawBasisLine(results({ law: { ...results().law!, ordinance: receipt, evidence, sources: [{ title: '건축법', date: '2025-01-01' }], truncated: false } }), target)
  expect(withReceipt).toEqual({
    kind: 'progress', agent: 'law', tone: 'ok',
    text: '법적 근거 6건 (기준일 2026-10-08) · 전제: 층고 3.8 m 가정, 지반고 미측정, 접도 방향 추정 (도로 미검증)',
    card: { type: 'links', items: [
      { label: '의정부시 도시계획 조례', href: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2072835', note: '판본 2072835 · 시행 2025-09-25' },
      { label: '의정부시 도시계획 조례 제42조' }, { label: '의정부시 도시계획 조례 제46조' }, { label: '건축법 제60조, 국토계획법 시행령 제80조' },
      { label: '건축법', note: '2025-01-01' },
      { label: '스냅샷은 개정 완전성을 보증하지 않음', note: '유의' },
    ] },
    actions: [related],
  })
  const cut = lawBasisLine(results(), target)
  expect(cut).toEqual({ kind: 'progress', agent: 'law', tone: 'warn', text: '조례 영수증이 전달되지 않았어요 — Law 응답이 8,000자에서 잘렸어요', actions: [related] })
  expect(lawBasisLine(results({ law: { ...results().law!, truncated: false } }), target)).toBeNull()
  expect(lawBasisLine(results({ law: null }), target)).toBeNull()
})

test("the law card carries Law's numbers as stat tiles with their article and ceiling, the capacities and the height rule", () => {
  expect(lawCard(results())).toEqual({ type: 'stats', items: [
    // A storey cap is the district plan's 획지 decision, so its note names that, not a height article.
    { label: '대지면적', value: '2,499.7㎡' }, { label: '건폐율', value: '59.92%' }, { label: '용적률', value: '249.67%' }, { label: '최고 층수', value: '5층', hint: '지구단위계획 획지 결정' },
  ] })
  const whole = results({ law: { ...results().law!, site_area_m2: 1006.531, bcr_pct: 20, far_pct: 80, max_floors: null, ground_capacity_m2: 201.306, far_capacity_m2: 805.225,
    zones: ['자연녹지지역'], national_bcr_ceiling_pct: 20, national_far_ceiling_pct: 100,
    articles: { bcr: '의정부시 도시계획 조례 제42조', far: '의정부시 도시계획 조례 제46조', height: '건축법 제60조, 국토계획법 시행령 제80조' }, height: { status: 'no_height_overlay', limit_m: null } } })
  expect(lawLine(whole)).toBe('법규 한계 (자연녹지지역): 건폐 20% · 용적 80%')
  expect(lawCard(whole)).toEqual({ type: 'stats', items: [
    { label: '대지면적', value: '1,006.5㎡' },
    { label: '건폐율', value: '20%', hint: '의정부시 도시계획 조례 제42조 · 국가 상한 20%' },
    { label: '용적률', value: '80%', hint: '의정부시 도시계획 조례 제46조 · 국가 상한 100%' },
    { label: '건축면적 상한', value: '201.3㎡', hint: '건폐율 × 대지면적' },
    { label: '연면적 상한', value: '805.2㎡', hint: '용적률 × 대지면적' },
    { label: '높이 제한', value: '높이 지구 없음', hint: '건축법 제60조, 국토계획법 시행령 제80조' },
  ] })
  expect(lawCard(results({ law: { ...results().law!, site_area_m2: null, max_floors: null } }))).toEqual({ type: 'stats', items: [
    { label: '건폐율', value: '59.92%' }, { label: '용적률', value: '249.67%' }, { label: '높이 제한', value: '—' },
  ] })
  expect(lawCard(results({ law: null }))).toBeNull()
})

test("the Site Agent's answer is its eight facts: established with provenance, missing as its own finding, unread when cut", () => {
  const line = siteFactsLine(results())!
  expect(line.kind).toBe('progress')
  expect(line.agent).toBe('site_context')
  expect(line.tone).toBe('warn')
  expect(line.text).toBe('대지 사실 5/8 확인 — 미제공: 출입구·접근, 설비 인입, 재해 위험')
  expect(line.card).toEqual({ type: 'checks', items: [
    { label: '대지 경계', state: 'ok', note: '면적 2,499.69㎡ · 공식 자료 · 2026-10-08', critical: true },
    { label: '접도 도로', state: 'ok', note: '접도 5건 · 폭 15m, 20m · 공식 자료 · 2026-10-08', critical: true },
    { label: '출입구·접근', state: 'missing', note: '미제공', critical: false },
    { label: '정북·진북', state: 'unread', note: '응답이 잘려 읽지 못함', critical: true },
    { label: '지형·표고', state: 'unread', note: '응답이 잘려 읽지 못함', critical: false },
    { label: '설비 인입', state: 'missing', note: '미제공', critical: false },
    { label: '재해 위험', state: 'missing', note: '미제공', critical: false },
    { label: '주변 맥락', state: 'unread', note: '응답이 잘려 읽지 못함', critical: false },
  ] })
  // A fact the Site Agent stored as `unknown` is missing even without a finding; a failed site step names its code.
  const unknown = { key: 'site.north', confidence: 'unknown', source: null, as_of: null, summary: null }
  expect((siteFactsLine(results({ site: { ...results().site!, facts: [...siteFacts, unknown] } }))!.card as { items: { label: string; state: string }[] }).items[3]).toEqual({ label: '정북·진북', state: 'missing', note: '미제공', critical: true })
  expect(siteFactsLine(results({ site: { status: 'failed', code: 'parcels_not_contiguous', facts_known: null, facts_total: null, facts_missing: [], facts: [] } })))
    .toEqual({ kind: 'error', agent: 'site_context', text: '대지 사실 확인 실패 — 필지가 서로 붙어 있지 않음' })
  expect(siteFactsLine(results({ site: null }))).toBeNull()
})

test("the Revision Agent's triage lists every finding: what, who raised it, its category, the action and its owner", () => {
  const actions = [
    { finding: 'SITE-ACCESS', raised_by: 'site_context', category: 'site_fact_missing', recommended_action: 're-run: site_context', recommended_agents: ['site_context'], evidence: null },
    { finding: 'law.district_review.0333', raised_by: 'law', category: 'district_assessment_input',
      recommended_action: 'Supply an explicit valid assessment date; Law cannot choose a date or legal edition on the user behalf.', recommended_agents: ['user'], evidence: null },
  ]
  const line = revisionLine(results({ review: { ...results().review!, actions } }))!
  expect(line.agent).toBe('revision')
  expect(line.tone).toBe('warn')
  expect(line.text).toBe('재검토 판정: 사용자 입력 필요 — 제기 2건')
  expect(line.card).toEqual({ type: 'findings', items: [
    { title: '대지 접근(출입구·접도)', by: 'Site Agent', category: '대지 사실 누락', action: 'Site Agent 재실행', owners: 'Site Agent' },
    { title: '지구단위계획 검토 (법규)', by: 'Law Agent', category: '지구단위 검토 입력 필요', action: '기준일을 명시해 주세요 — 법규 에이전트는 날짜·법령 판본을 대신 고르지 않아요', owners: '사용자' },
  ] })
  expect(revisionLine(results({ review: { status: 'succeeded', code: null, missing_evidence: [], actions: [] } }))).toEqual({ kind: 'progress', agent: 'revision', tone: 'ok', text: '재검토 판정: 성공' })
  expect(revisionLine(results({ review: null }))).toBeNull()
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
    { label: '법규 검토 결과 보기', artifact: 'law', params: { pnu: '4115011300106840001', tab: 'orchestrator', address: '산곡동 684-1', project: 'p1' } },
    { label: '관련 법규 보기', artifact: 'law', params: { pnu: '4115011300106840001', tab: 'articles', address: '산곡동 684-1', project: 'p1' } },
    { label: '협업 흐름 보기', artifact: 'collaboration', params: { project: 'p1', run: 'r', tab: 'log' } },
    { label: '나중에' },
  ])
  expect(resultPrompt(results({ law: null }), target).text).toBe('근거가 부족해 법규 한계를 확정하지 못했어요. 법규를 보시겠어요?')
  expect(resultPrompt(results({ status: 'completed', review: null, missing_evidence_all: [] }), { pnu: 'x' }).text).toBe('법규 검토가 끝났어요. 법규를 보시겠어요?')
  expect(resultPrompt(results({ status: 'completed', review: null, missing_evidence_all: [] }), { pnu: 'x' }).actions.map((action) => action.label)).toEqual(['법규 검토 결과 보기', '관련 법규 보기', '협업 흐름 보기', '나중에'])
  const failed = resultPrompt(results({ status: 'failed' }), target)
  expect(failed.text).toBe('검토가 실패했어요. 어디서 멈췄는지 법규 패널에서 보시겠어요?')
  expect(failed.actions.map((action) => action.label)).toEqual(['법규 검토 결과 보기', '협업 흐름 보기', '시스템 보기', '나중에'])
})

test('the law line carries the caps and floors as the UI shows them (the area lives in the tiles)', () => {
  expect(lawLine(results())).toBe('법규 한계: 건폐 59.92% · 용적 249.67% · 5층')
  expect(lawLine(results({ law: null }))).toBeNull()
  expect(lawLine(results({ law: { ...results().law!, site_area_m2: null, max_floors: null } }))).toBe('법규 한계: 건폐 59.92% · 용적 249.67%')
  // Inside a 지구단위계획구역 with no lot rule applied: the numbers are ordinance ceilings, and the line says so.
  expect(lawLine(results({ law: { ...results().law!, district_plan_review_needed: true } })))
    .toBe('법규 한계: 건폐 59.92% · 용적 249.67% · 5층\n지구단위계획구역 안 — 이 값은 조례 상한이며 획지 값은 지구단위 검토에서 정해집니다')
  // The Orchestrator refused Law's caps and no number stands: the refusal is the line.
  const refused = { ...results().law!, bcr_pct: null, far_pct: null, max_floors: null, height: { status: null, limit_m: null }, code: 'limits_zoning_mismatch' }
  expect(lawLine(results({ law: refused }))).toBe('Law가 계산한 용도지역 분할이 Site의 읽기와 달라 그 상한은 채택하지 않았어요')
  expect(lawLine(results({ law: { ...refused, code: 'something_else' } }))).toBeNull()
})

test('the verdict line says 보류 with the short missing-evidence list, or the failure code', () => {
  expect(resultLine(results())).toBe('검토 결과: 보류 — 근거 보충 필요: 기준일, 대지 접근·재해·설비')
  expect(resultLine(results({ status: 'failed', site: { status: 'failed', code: 'parcels_not_contiguous', facts_known: null, facts_total: null, facts_missing: [] } })))
    .toBe('검토 결과: 실패 — 필지가 서로 붙어 있지 않음')
  expect(resultLine(results({ status: 'completed', review: null, missing_evidence_all: [] }))).toBe('검토 결과: 완료')
  // a 배치 설계 that ended as a selection set asks for the pick, whatever its status says
  expect(resultLine(results({ status: 'blocked', goal: 'masterplan', masterplan: { status: 'needs_evidence', code: 'masterplan_alternative_selection_required', task_id: null, truncated: false, layout: null, intent: null } })))
    .toBe('배치안이 나왔어요 — 대지 지도의 3D 보기에서 하나를 골라 주세요')
  // Law gave no parking count twice: the line says so and asks the person for nothing
  expect(resultLine(results({ status: 'blocked', goal: 'masterplan', masterplan: { status: 'needs_evidence', code: 'law_parking_count_missing', task_id: null, truncated: false, layout: null, intent: null } })))
    .toBe('법규 에이전트가 주차 대수를 아직 내지 못해 배치를 멈췄어요 — 사용자가 넣을 값은 없어요')
})

test('a run waiting on the person names the condition it asks for and says no agent was called yet', () => {
  const waiting = results({ status: 'waiting_input', pending_input: true, pending_fields: ['building_type'], steps: [], review: null, missing_evidence_all: [] })
  expect(resultLine(waiting)).toBe('검토를 시작하기 전에 용도를 물어요 — 아직 에이전트를 부르지 않았어요')
  const prompt = resultPrompt(waiting, { pnu: '4115011300106840001', address: '산곡동 684-1' })
  expect(prompt.text).toBe('용도를 고르고 다시 검토를 누르면 대지 → 법규 순서로 이어가요. 법규 패널에서 채우시겠어요?')
  expect(prompt.actions.map((action) => action.label)).toEqual(['조건 채우기', '나중에'])
})

test('activation: the Orchestrator says whom it is waking, names what did not come up without submitting, and the handoff button says 켜고 시작', () => {
  expect(activatingLine(['program', 'mass'])).toEqual({ kind: 'progress', agent: 'orchestrator', tone: 'busy', relay: { from: 'orchestrator', to: 'program' }, text: 'Program Agent · Mass Agent 켜는 중 (병렬 2)' })
  expect(activatingLine(['law']).text).toBe('Law Agent 켜는 중')
  expect(activationFailedLine([{ agent: 'mass', error: 'ECONNREFUSED' }], { kind: 'start-review', goal: 'limits' })).toEqual({
    kind: 'error', agent: 'orchestrator', text: 'Mass Agent (ECONNREFUSED)이(가) 켜지지 않았어요 — 검토를 보내지 않았어요',
    actions: [{ label: '다시 시도', command: { kind: 'start-review', goal: 'limits' } }, { label: '시스템 보기', artifact: 'system' }] })
  const open: AskAnswer = { question: '매스 쌓아 봐', agent: 'mass', tool: null, trace_id: null, version: null, answer: null,
    route: { kind: 'goal', agent: 'mass', skill: null, goal: 'mass', confidence: 0.7, reason: 'r', choices: [] },
    handoff: { goal: 'mass', label: '매스 생성', owners: ['program', 'masterplan', 'mass', 'revision'], available: true } }
  const line = answerLine(open, null, ['program', 'mass'])
  expect(line.actions?.[0]).toEqual({ label: '켜고 시작 (2개)', command: { kind: 'start-review', goal: 'mass' } })
  expect(line.text).toContain('Program Agent · Mass Agent은(는) 꺼져 있어 먼저 켜요')
  expect(answerLine(open, null).actions?.[0]?.label).toBe('매스 생성 시작')
})


test('an address the backend located becomes the Site Agent line that opens the map on that parcel and selects it', () => {
  const route = { kind: 'skill', agent: 'site_context', skill: 'site_locate', goal: null, confidence: 0.95, reason: '주소를 적었어요', choices: [], decided_by: 'pattern', instruction: null } as const
  const base: AskAnswer = { question: '의정부시 산곡동 684-1', route, agent: 'site_context', tool: 'site_locate', trace_id: null, version: null, handoff: null, answer: null }
  const found = siteLocatedLine({ kind: 'site', query: '의정부시 산곡동 684-1', pnu: '4115011300106840001', address: '경기도 의정부시 산곡동 684-1', coordinates: { x: 127.1, y: 37.7 }, error: null })
  expect(found).toEqual({ kind: 'progress', agent: 'site_context', tone: 'ok', text: '지도에서 찾았어요 — 경기도 의정부시 산곡동 684-1 · 이 필지를 대지로 선택해요',
    actions: [{ label: '지도 보기', artifact: 'site-map', params: { pnu: '4115011300106840001', pick: '1' } }] })
  // The general answer line hands a site answer to the Site Agent's line (every answer kind has a turn).
  expect(answerLine({ ...base, answer: { kind: 'site', query: 'q', pnu: '4115011300106840001', address: null, coordinates: null, error: null } }, null)).toMatchObject({ agent: 'site_context', tone: 'ok' })
  const missing = siteLocatedLine({ kind: 'site', query: '없는동 1', pnu: null, address: null, coordinates: null, error: 'Address lookup returned no usable result' })
  expect(missing).toMatchObject({ agent: 'site_context', tone: 'warn', actions: [{ label: '지도 열기', artifact: 'site-map' }] })
  // Geocoded without a PNU: the map resolves the address itself (reverse lookup at the point).
  expect(siteLocateParams({ kind: 'site', query: '테헤란로 152', pnu: null, address: null, coordinates: { x: 1, y: 2 }, error: null })).toEqual({ address: '테헤란로 152', pick: '1' })
})

test('a question that belongs to a registered agent without a role module is named in the agent\'s card words and offered to the conversation', () => {
  const delegated: AskAnswer = { question: '기둥 간격 어떻게?', agent: 'structure', tool: null, trace_id: null, version: null, answer: null, handoff: null,
    route: { kind: 'agent', agent: 'structure', skill: null, goal: null, confidence: 0.85, reason: '구조 질문이에요', choices: [], decided_by: 'llm', instruction: '이 매스의 골조 안을 내 주세요' },
    delegate: { agent: 'structure', label: 'StructureAgent', description: 'Frames and walls for a mass.', instruction: '이 매스의 골조 안을 내 주세요', skills: [{ id: 'structure_frame', name: 'frame' }], available: true } }
  expect(answerLine(delegated, null)).toEqual({ kind: 'prompt', agent: 'orchestrator',
    text: '이건 StructureAgent의 일이에요 · StructureAgent에게: "이 매스의 골조 안을 내 주세요" — Frames and walls for a mass.',
    card: { type: 'chips', items: ['frame'] },
    actions: [{ label: '대화로 보내기', command: { kind: 'compose', draft: '기둥 간격 어떻게?' } }, { label: '나중에' }] })
  expect(answerLine({ ...delegated, delegate: { ...delegated.delegate!, available: false, description: null, instruction: null, skills: [] } }, null).text)
    .toBe('이건 StructureAgent의 일이에요 (지금은 응답하지 않아요)')
})

test('a run waiting for the district lot asks in the conversation, not in a panel', () => {
  const question = { kind: 'request_input', code: 'district_lot_required', fields: ['district_lot'],
    candidates: { status: 'parcel_not_tied_to_a_lot_choose_one', lots: [{ lot: '공공1', far_pct_max: [{ value: 250 }] }] } }
  const prompt = resultPrompt(results({ status: 'waiting_input', pending_fields: ['district_lot'], pending_request: question }), { pnu: '4115011300106840001' })
  expect(prompt.text).toContain('어느 획지인지')
  expect(prompt.actions.map((action) => action.label)).toEqual(['나중에'])
})
