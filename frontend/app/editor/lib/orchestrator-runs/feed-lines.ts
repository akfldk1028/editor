/** Feed lines from run snapshots and parsed results. Pure: the hooks decide when to post. */
import type { RunConditions } from './conditions'
import type { FeedAction, FeedCard, FeedInput, FeedTone } from './feed'
import {
  actionLabel, agentForTool, agentLabel, categoryLabel, confidenceLabel, evidenceLabel, frontageLabel, heightLabel, limitationLabel, SITE_FACTS,
  shortEvidence, stateLabel, toolLabel, traceLabel, verdictLabel,
} from './labels'
import { failureText, type RunFailure } from './submit'
import type { Communication, OrchestratorConnection, RunResults, RunSummary } from './types'

const fmt = (value: number, digits: number) => value.toLocaleString('ko-KR', { maximumFractionDigits: digits })

export interface SelectedSite {
  label: string
  parcels: readonly { pnu: string; address?: string }[]
  total_area_m2: number | null
}

/** "대지 선택: 경기도 의정부시 산곡동 684-1 (1필지, 2,499.98㎡)" */
export function selectedLine(site: SelectedSite): string {
  const area = site.total_area_m2 === null ? '' : `, ${fmt(site.total_area_m2, 2)}㎡`
  return `대지 선택: ${site.label} (${site.parcels.length}필지${area})`
}

const ORCHESTRATOR = 'orchestrator'

/**
 * Once the site is saved and the Orchestrator answers: it asks what to do, and the user chooses —
 * 법규·한계 검토 시작 (a command the site card carries out), 대지 정보 보기, 법규 요약 보기.
 */
export function selectedPrompt(site: SelectedSite): FeedInput {
  const first = site.parcels[0]!
  const target = { pnu: first.pnu, ...(first.address || site.label ? { address: first.address || site.label } : {}) }
  return {
    kind: 'prompt',
    agent: ORCHESTRATOR,
    text: `${site.label} — 무엇을 할까요?`,
    actions: [
      { label: '법규·한계 검토 시작', command: { kind: 'start-review', goal: 'limits' } },
      { label: '대지 정보 보기', artifact: 'site-map' },
      { label: '법규 요약 보기', artifact: 'law', params: { ...target, tab: 'summary' } },
    ],
  }
}

export function connectionLine(connection: OrchestratorConnection): FeedInput {
  if (connection.state === 'up') return { kind: 'system', agent: ORCHESTRATOR, text: `Orchestrator Agent 연결됨 · 에이전트 ${connection.agentsUp}/${connection.agentsTotal}` }
  return {
    kind: 'error',
    agent: ORCHESTRATOR,
    text: connection.state === 'invalid' ? 'Orchestrator Agent 응답 형식이 맞지 않아요' : 'Orchestrator Agent에 연결할 수 없어요',
    actions: [{ label: '시스템 보기', artifact: 'system' }],
  }
}

/**
 * The moment 검토 시작 is pressed: the user's bubble ("검토 시작 · 산곡동 684-1 · 기준일 2026-10-08 · 용도
 * 업무시설") and the Orchestrator's busy line until the receipt arrives.
 */
export function requestingLines(label: string, conditions: Pick<RunConditions, 'assessmentDate' | 'buildingType'>): FeedInput[] {
  const use = conditions.buildingType.trim()
  return [
    { kind: 'user', text: `검토 시작 · ${label} · 기준일 ${conditions.assessmentDate}${use ? ` · 용도 ${use}` : ''}` },
    { kind: 'progress', agent: ORCHESTRATOR, tone: 'busy', text: '요청 보내는 중' },
  ]
}

/** "검토 요청 실패 — 오케스트레이터에 연결할 수 없어요", with 시스템 보기 when it is unreachable. */
export function requestFailedLine(failure: RunFailure): FeedInput {
  return {
    kind: 'error',
    agent: ORCHESTRATOR,
    text: `검토 요청 실패 — ${failureText(failure)}`,
    ...(failure.kind === 'unavailable' ? { actions: [{ label: '시스템 보기', artifact: 'system' }] } : {}),
  }
}

/** "검토 요청 접수 · run 8c7f6fb7 · trace 4bf92f35" */
export function submittedLine(run: Pick<RunSummary, 'run_id' | 'trace_id'>): string {
  return `검토 요청 접수 · run ${traceLabel(run.run_id)}${run.trace_id ? ` · trace ${traceLabel(run.trace_id)}` : ''}`
}

interface ParsedResponse {
  status?: unknown
  code?: unknown
  summary?: unknown
}

function parsed(text: string | null): ParsedResponse {
  if (!text) return {}
  try {
    const value: unknown = JSON.parse(text)
    return value && typeof value === 'object' ? (value as ParsedResponse) : {}
  } catch {
    // A response cut at 8000 characters: the leading `"status": "..."` is still readable.
    const status = text.match(/"status":\s*"([a-z_]+)"/)?.[1]
    const summary = text.match(/"summary":\s*"([^"]*)"/)?.[1]
    return { ...(status ? { status } : {}), ...(summary ? { summary } : {}) }
  }
}

const OWN_STATES = new Set(['needs_evidence', 'failed', 'succeeded'])

/** A step's state: the tool's own `status` when it is one of ours (revision says needs_evidence while its task failed), else the record's. */
export function stepState(comm: Pick<Communication, 'state' | 'response_text'>): string {
  const own = parsed(comm.response_text).status
  return typeof own === 'string' && OWN_STATES.has(own) ? own : comm.state
}

/** The dot before a step line: green when the step succeeded, amber when it wants evidence or failed, spinning while open. */
export function stepTone(state: string): FeedTone {
  if (state === 'succeeded' || state === 'completed' || state === 'complete') return 'ok'
  if (state === 'running' || state === 'queued' || state === 'pending') return 'busy'
  return 'warn'
}

export interface StepChange {
  key: string
  tool: string
  text: string
  tone: FeedTone
  /** The agent that spoke: the record's, else the tool's owner. */
  agent: string | null
}

/** While a step runs, the Orchestrator says whom it is asking: "Law Agent에게 법규 한계 요청 중" (busy). */
export function relayLine(change: Pick<StepChange, 'tool' | 'agent'>): FeedInput {
  return { kind: 'progress', agent: ORCHESTRATOR, tone: 'busy', text: `${agentLabel(change.agent ?? ORCHESTRATOR)}에게 ${toolLabel(change.tool)} 요청 중` }
}

/** "대지 · 대지 사실 확인: 근거 부족 (5/8 사실)" — one per step whose state is new or changed since `prev`. */
export function stepChanges(prev: Pick<RunSummary, 'communications'> | null, next: Pick<RunSummary, 'communications'>): StepChange[] {
  const before = new Map((prev?.communications ?? []).map((comm) => [comm.tool, stepState(comm)]))
  const lines: StepChange[] = []
  for (const comm of next.communications) {
    const state = stepState(comm)
    if (before.get(comm.tool) === state) continue
    const response = parsed(comm.response_text)
    const facts = typeof response.summary === 'string' ? response.summary.match(/(\d+)\s*\/\s*(\d+)\s*site facts/) : null
    const detail = facts ? ` (${facts[1]}/${facts[2]} 사실)` : typeof response.code === 'string' && state === 'failed' ? ` — ${evidenceLabel(response.code)}` : ''
    const agent = agentForTool(comm.tool, comm.agent)
    lines.push({
      key: `${comm.tool}:${state}`,
      tool: comm.tool,
      text: `${toolLabel(comm.tool)}: ${stateLabel(state)}${detail}`,
      tone: stepTone(state),
      agent,
    })
  }
  return lines
}

/**
 * The Site Agent's answer as its eight facts (`facts.py` SITE_KEYS): each one established (with its
 * confidence, date and a one-line value), missing (its own SITE-* finding), or unread (the 8000-character
 * cap cut the answer before it). Null until the site step answered.
 */
export function siteFactsLine(results: RunResults): FeedInput | null {
  const site = results.site
  if (!site) return null
  if (site.code) return { kind: 'error', agent: 'site_context', text: `대지 사실 확인 실패 — ${evidenceLabel(site.code)}` }
  const read = new Map(site.facts.map((fact) => [fact.key, fact]))
  const missing = new Set(site.facts_missing)
  const items = SITE_FACTS.map((fact) => {
    const found = read.get(fact.key)
    if (missing.has(fact.code) || found?.confidence === 'unknown') return { label: fact.label, state: 'missing' as const, note: '미제공', critical: fact.critical }
    if (found) {
      const note = [found.summary, confidenceLabel(found.confidence), found.as_of].filter((part): part is string => Boolean(part)).join(' · ')
      return { label: fact.label, state: 'ok' as const, note, critical: fact.critical }
    }
    return { label: fact.label, state: 'unread' as const, note: '응답이 잘려 읽지 못함', critical: fact.critical }
  })
  const known = site.facts_known !== null && site.facts_total !== null ? `${site.facts_known}/${site.facts_total}` : `${items.filter((item) => item.state === 'ok').length}/${items.length}`
  const lacking = items.filter((item) => item.state === 'missing').map((item) => item.label)
  const text = `대지 사실 ${known} 확인${lacking.length ? ` — 미제공: ${lacking.join(', ')}` : ''}`
  return { kind: 'progress', agent: 'site_context', tone: lacking.length ? 'warn' : 'ok', text, card: { type: 'checks', items } }
}

/** "법규 한계 (자연녹지지역): 건폐 20% · 용적 80% · 5층" — Law speaking; null until its numbers arrive. */
export function lawLine(results: RunResults): string | null {
  const law = results.law
  if (!law) return null
  const parts = [
    law.bcr_pct !== null ? `건폐 ${fmt(law.bcr_pct, 2)}%` : null,
    law.far_pct !== null ? `용적 ${fmt(law.far_pct, 2)}%` : null,
    law.max_floors !== null ? `${law.max_floors}층` : law.height.limit_m !== null ? `높이 ${law.height.limit_m} m` : null,
  ].filter((part): part is string => part !== null)
  if (!parts.length) return null
  return `법규 한계${law.zones.length ? ` (${law.zones.join(' · ')})` : ''}: ${parts.join(' · ')}`
}

/**
 * Law's numbers as stat tiles under the law line, each with where it comes from: the ordinance article
 * and the national ceiling for the caps, the capacities Law derived from them, and the height rule.
 */
export function lawCard(results: RunResults): FeedCard | null {
  const law = results.law
  if (!law) return null
  const ceiling = (value: number | null) => (value !== null ? `국가 상한 ${fmt(value, 2)}%` : null)
  const hint = (...parts: (string | null)[]) => {
    const text = parts.filter((part): part is string => Boolean(part)).join(' · ')
    return text ? { hint: text } : {}
  }
  const items = [
    law.site_area_m2 !== null ? { label: '대지면적', value: `${fmt(law.site_area_m2, 1)}㎡` } : null,
    law.bcr_pct !== null ? { label: '건폐율', value: `${fmt(law.bcr_pct, 2)}%`, ...hint(law.articles.bcr, ceiling(law.national_bcr_ceiling_pct)) } : null,
    law.far_pct !== null ? { label: '용적률', value: `${fmt(law.far_pct, 2)}%`, ...hint(law.articles.far, ceiling(law.national_far_ceiling_pct)) } : null,
    law.ground_capacity_m2 !== null ? { label: '건축면적 상한', value: `${fmt(law.ground_capacity_m2, 1)}㎡`, hint: '건폐율 × 대지면적' } : null,
    law.far_capacity_m2 !== null ? { label: '연면적 상한', value: `${fmt(law.far_capacity_m2, 1)}㎡`, hint: '용적률 × 대지면적' } : null,
    law.max_floors !== null
      ? { label: '최고 층수', value: `${law.max_floors}층`, ...hint(law.articles.height) }
      : { label: '높이 제한', value: heightLabel(law.height.status, law.height.limit_m), ...hint(law.articles.height) },
  ].filter((item): item is { label: string; value: string; hint?: string } => item !== null)
  return items.length ? { type: 'stats', items } : null
}

/** Where 법규 보기 lands: the law artifact on this site, under the run's binding. */
export interface LawTarget {
  pnu: string
  address?: string
  project?: string
}

const lawParams = (target: LawTarget, tab: string) => ({ pnu: target.pnu, tab, ...(target.address ? { address: target.address } : {}), ...(target.project ? { project: target.project } : {}) })

/** "20250925" → "2025-09-25"; other shapes stay. */
const isoDate = (value: string) => (/^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : value)

/**
 * Law Agent's legal basis for this land — the ordinance receipt (articles, edition, effective date)
 * and its sources as chips — with 관련 법규 보기, which opens every regulation and article the editor
 * finds for the parcel (law artifact, 조문 tab). Null when Law sent nothing of the kind.
 */
export function lawBasisLine(results: RunResults, target: LawTarget): FeedInput | null {
  const law = results.law
  if (!law) return null
  const action: FeedAction = { label: '관련 법규 보기', artifact: 'law', params: lawParams(target, 'articles') }
  const items: { label: string; href?: string; note?: string }[] = []
  for (const source of law.ordinance?.sources ?? []) {
    const note = [source.edition_id ? `판본 ${source.edition_id}` : null, source.effective_date ? `시행 ${isoDate(source.effective_date)}` : null].filter(Boolean).join(' · ')
    items.push({ label: source.name ?? '조례', ...(source.url ? { href: source.url } : {}), ...(note ? { note } : {}) })
  }
  for (const article of law.ordinance?.articles ?? []) items.push({ label: article })
  for (const source of law.sources) items.push({ label: source.title ?? '—', ...(source.date ? { note: source.date } : {}) })
  for (const code of law.ordinance?.limitations ?? []) items.push({ label: limitationLabel(code), note: '유의' })
  const assumptions = [
    law.evidence.floor_height_m !== null ? `층고 ${law.evidence.floor_height_m} m 가정` : null,
    law.evidence.datum_measured === false ? '지반고 미측정' : law.evidence.datum_measured === true ? '지반고 측정' : null,
    frontageLabel(law.evidence.frontage_grade),
  ].filter((part): part is string => Boolean(part))
  const premise = assumptions.length ? ` · 전제: ${assumptions.join(', ')}` : ''
  if (law.ordinance) {
    const { assessment_date } = law.ordinance
    const dated = assessment_date ? ` (기준일 ${assessment_date})` : ''
    return { kind: 'progress', agent: 'law', tone: 'ok', text: `법적 근거 ${items.length}건${dated}${premise}`, card: items.length ? { type: 'links', items } : undefined, actions: [action] }
  }
  if (items.length) return { kind: 'progress', agent: 'law', tone: 'ok', text: `법적 근거 ${items.length}건${premise}`, card: { type: 'links', items }, actions: [action] }
  if (law.truncated) return { kind: 'progress', agent: 'law', tone: 'warn', text: `조례 영수증이 전달되지 않았어요 — Law 응답이 8,000자에서 잘렸어요${premise}`, actions: [action] }
  return null
}

/**
 * The Revision Agent's triage as it wrote it: its verdict code and every finding it weighed — what,
 * who raised it, its category, the recommended action and who should carry it out. Null before it ran.
 */
export function revisionLine(results: RunResults): FeedInput | null {
  const review = results.review
  if (!review) return null
  const items = review.actions.map((action) => ({
    title: evidenceLabel(action.finding ?? '—'),
    by: agentLabel(action.raised_by),
    category: categoryLabel(action.category),
    action: actionLabel(action.recommended_action),
    owners: action.recommended_agents.map(agentLabel).join(', '),
  }))
  const verdict = review.code ? stateLabel(review.code) : stateLabel(review.status)
  const text = `재검토 판정: ${verdict}${items.length ? ` — 제기 ${items.length}건` : ''}`
  const tone: FeedTone = review.status === 'succeeded' || review.status === 'completed' ? 'ok' : 'warn'
  return { kind: 'progress', agent: 'revision', tone, text, ...(items.length ? { card: { type: 'findings', items } } : {}) }
}

/** The missing evidence as Korean chips (codes only, each once); null when nothing is missing. */
export function evidenceCard(results: RunResults): FeedCard | null {
  const items = [...new Set(results.missing_evidence_all.filter((code) => !code.includes(': ')).map(evidenceLabel))]
  return items.length ? { type: 'chips', items } : null
}

/** "검토 결과: 보류 — 근거 보충 필요: 기준일, 대지 접근·재해·설비" */
export function resultLine(results: RunResults): string {
  const verdict = verdictLabel(results.status, results.review?.code)
  if (results.status === 'failed') {
    const code = results.site?.code
    return `검토 결과: 실패${code ? ` — ${evidenceLabel(code)}` : ''}`
  }
  const missing = shortEvidence(results.missing_evidence_all)
  return `검토 결과: ${verdict}${verdict.includes('근거') && missing ? `: ${missing}` : ''}`
}

/**
 * The question the network asks once a run ended — "법규를 보시겠어요?" with 법규 보기 (the run's review
 * tab) and 관련 법규 보기 (every regulation and article for the land) as answers, 나중에 to dismiss.
 * After a failure it offers 시스템 보기 as well.
 */
export function resultPrompt(results: RunResults, target: LawTarget): { text: string; actions: FeedAction[] } {
  const law: FeedAction = { label: '법규 보기', artifact: 'law', params: lawParams(target, 'orchestrator') }
  const related: FeedAction = { label: '관련 법규 보기', artifact: 'law', params: lawParams(target, 'articles') }
  const later: FeedAction = { label: '나중에' }
  if (results.status === 'failed') {
    return { text: '검토가 실패했어요. 어디서 멈췄는지 법규 패널에서 보시겠어요?', actions: [law, { label: '시스템 보기', artifact: 'system' }, later] }
  }
  if (verdictLabel(results.status, results.review?.code).includes('근거')) {
    const numbers = results.law && (results.law.bcr_pct !== null || results.law.far_pct !== null)
    return {
      text: numbers ? '법규 한계는 나왔지만 근거가 더 필요해요. 법규를 보시겠어요?' : '근거가 부족해 법규 한계를 확정하지 못했어요. 법규를 보시겠어요?',
      actions: [law, related, later],
    }
  }
  return { text: '법규 검토가 끝났어요. 법규를 보시겠어요?', actions: [law, related, later] }
}
