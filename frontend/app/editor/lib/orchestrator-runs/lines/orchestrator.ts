/**
 * What the Orchestrator Agent (and the user) say in the conversation: the site picked and the
 * question that follows, connection, the request going out, receipts, every step as it changes,
 * the verdict and the closing question. Pure: the hooks decide when to post.
 */
import type { RunConditions } from '../conditions'
import type { FeedAction, FeedCard, FeedInput, FeedTone } from '../feed'
import { agentForTool, agentLabel, evidenceLabel, shortEvidence, stateLabel, toolLabel, traceLabel, verdictLabel } from '../labels'
import { failureText, type RunFailure } from '../submit'
import type { Communication, OrchestratorConnection, RunResults, RunSummary } from '../types'
import { fmt, type LawTarget, lawParams, ORCHESTRATOR } from './shared'

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
 * 업무시설") and the request drawn (user ⟶ Orchestrator Agent) until the receipt arrives.
 */
export function requestingLines(label: string, conditions: Pick<RunConditions, 'assessmentDate' | 'buildingType'>): FeedInput[] {
  const use = conditions.buildingType.trim()
  return [
    { kind: 'user', text: `검토 시작 · ${label} · 기준일 ${conditions.assessmentDate}${use ? ` · 용도 ${use}` : ''}` },
    { kind: 'progress', agent: ORCHESTRATOR, tone: 'busy', relay: { from: 'user', to: ORCHESTRATOR }, text: 'Orchestrator Agent에게 검토 요청 중' },
  ]
}

/** "검토 요청 실패 — Orchestrator Agent에 연결할 수 없어요", with 시스템 보기 when it is unreachable. */
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

/** While a step runs, the Orchestrator says whom it is asking — drawn as Orchestrator Agent ⟶ that agent. */
export function relayLine(change: Pick<StepChange, 'tool' | 'agent'>): FeedInput {
  const to = change.agent ?? ORCHESTRATOR
  return { kind: 'progress', agent: ORCHESTRATOR, tone: 'busy', relay: { from: ORCHESTRATOR, to }, text: `${agentLabel(to)}에게 ${toolLabel(change.tool)} 요청 중` }
}

/** "대지 사실 확인: 근거 부족 (5/8 사실)" — one per step whose state is new or changed since `prev`. */
export function stepChanges(prev: Pick<RunSummary, 'communications'> | null, next: Pick<RunSummary, 'communications'>): StepChange[] {
  const before = new Map((prev?.communications ?? []).map((comm) => [comm.tool, stepState(comm)]))
  const lines: StepChange[] = []
  for (const comm of next.communications) {
    const state = stepState(comm)
    if (before.get(comm.tool) === state) continue
    const response = parsed(comm.response_text)
    const facts = typeof response.summary === 'string' ? response.summary.match(/(\d+)\s*\/\s*(\d+)\s*site facts/) : null
    const detail = facts ? ` (${facts[1]}/${facts[2]} 사실)` : typeof response.code === 'string' && state === 'failed' ? ` — ${evidenceLabel(response.code)}` : ''
    lines.push({
      key: `${comm.tool}:${state}`,
      tool: comm.tool,
      text: `${toolLabel(comm.tool)}: ${stateLabel(state)}${detail}`,
      tone: stepTone(state),
      agent: agentForTool(comm.tool, comm.agent),
    })
  }
  return lines
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
