/**
 * What the Orchestrator Agent (and the user) say in the conversation: the site picked and the
 * question that follows, connection, the request going out, receipts, every step as it changes,
 * the verdict and the closing question. Pure: the hooks decide when to post.
 */
import type { RunConditions } from '@/lib/orchestrator-runs/conditions'
import type { FeedAction, FeedCard, FeedInput, FeedTone } from '@/lib/orchestrator-runs/feed'
import { agentForTool, agentLabel, askedFieldsLabel, evidenceLabel, shortEvidence, stateLabel, toolLabel, traceLabel, verdictLabel } from '@/lib/orchestrator-runs/labels'
import { failureText, type RunFailure } from '@/lib/orchestrator-runs/submit'
import type { AskAnswer, Capabilities, Communication, OrchestratorConnection, RunResults, RunSummary } from '@/lib/orchestrator-runs/types'
import { fmt } from '@/lib/orchestrator-runs/format'
import { type LawTarget, lawParams } from '@/lib/orchestrator-runs/law-target'
import { asksForLot } from '@/lib/run-question/lots'

const ORCHESTRATOR = 'orchestrator'

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
 * Once the site is saved and the Orchestrator answers: it asks what to do, and the user chooses.
 * The choices are derived from the goal catalog — one "<goal> 시작" command per goal the door takes
 * and the catalog offers — then 대지 정보 보기 and, when the conversation can ask Law, 법규 요약 보기.
 */
export function selectedPrompt(site: SelectedSite, capabilities: Capabilities): FeedInput {
  const starts: FeedAction[] = capabilities.goals
    .filter((goal) => goal.available && goal.offer)
    .map((goal): FeedAction => goal.id === 'limits'
      ? { label: '법규 검토', artifact: 'law', params: {
          tab: 'review',
          ...(site.parcels[0] ? { pnu: site.parcels[0].pnu, address: site.parcels[0].address || site.label, parcelCount: String(site.parcels.length) } : {}),
        } }
      : { label: goal.label, command: { kind: 'start-review', goal: goal.id } })
  return {
    kind: 'prompt',
    agent: ORCHESTRATOR,
    text: `${site.label} — 무엇을 할까요?`,
    actions: [
      { label: '설계 시작하기', command: { kind: 'compose', draft: '이 대지에서 설계를 시작하고 싶어요.' } },
      ...starts,
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

/**
 * The Orchestrator waking the agents a goal needs before it asks them (drawn Orchestrator ⟶ the first of
 * them; the text names all): "Program Agent · Mass Agent 켜는 중 (병렬 2)".
 */
export function activatingLine(agents: readonly string[]): FeedInput {
  const names = agents.map(agentLabel)
  return { kind: 'progress', agent: ORCHESTRATOR, tone: 'busy', relay: { from: ORCHESTRATOR, to: agents[0] ?? ORCHESTRATOR },
    text: `${names.join(' · ')} 켜는 중${agents.length > 1 ? ` (병렬 ${agents.length})` : ''}` }
}

/** Some of them did not come up: nothing is submitted (fail closed); the user may retry or look at the system. */
export function activationFailedLine(failed: readonly { agent: string; error: string }[], retry: FeedAction['command']): FeedInput {
  const text = failed.map((item) => `${agentLabel(item.agent)} (${item.error})`).join(', ')
  return { kind: 'error', agent: ORCHESTRATOR, text: `${text}이(가) 켜지지 않았어요 — 검토를 보내지 않았어요`,
    actions: [...(retry ? [{ label: '다시 시도', command: retry }] : []), { label: '시스템 보기', artifact: 'system' }] }
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
  if (results.status === 'waiting_input') {
    const asked = askedFieldsLabel(results.pending_fields)
    return asked ? `검토를 시작하기 전에 ${asked}를 물어요 — 아직 에이전트를 부르지 않았어요` : '검토를 시작하기 전에 조건을 물어요 — 아직 에이전트를 부르지 않았어요'
  }
  if (results.status === 'failed') {
    const code = results.site?.code
    return `검토 결과: 실패${code ? ` — ${evidenceLabel(code)}` : ''}`
  }
  if (results.masterplan?.code === 'masterplan_alternative_selection_required') {
    // The 배치 설계 ended as a selection set: the map's portfolio is where the person picks.
    return '배치안이 나왔어요 — 대지 지도의 3D 보기에서 하나를 골라 주세요'
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
  const law: FeedAction = { label: '법규 검토 결과 보기', artifact: 'law', params: lawParams(target, 'orchestrator') }
  const related: FeedAction = { label: '관련 법규 보기', artifact: 'law', params: lawParams(target, 'articles') }
  const flow: FeedAction = { label: '협업 흐름 보기', artifact: 'collaboration', params: { ...(target.project ? { project: target.project } : {}), ...(results.run_id ? { run: results.run_id } : {}), tab: 'log' } }
  const later: FeedAction = { label: '나중에' }
  if (results.status === 'waiting_input' && asksForLot(results.pending_request)) {
    // The lots are the conversation's waiting-question card (lib/run-question/useWaitingQuestions): answered there.
    return { text: '이 필지는 지구단위계획구역 안인데, 고시 문서에 어느 획지인지 적혀 있지 않아요. 아래에서 획지를 골라 주시면 그 규정으로 이어서 검토해요.', actions: [later] }
  }
  if (results.status === 'waiting_input') {
    const asked = askedFieldsLabel(results.pending_fields) || '조건'
    return { text: `${asked}를 고르고 다시 검토를 누르면 대지 → 법규 순서로 이어가요. 법규 패널에서 채우시겠어요?`, actions: [{ ...law, label: '조건 채우기' }, later] }
  }
  if (results.status === 'failed') {
    return { text: '검토가 실패했어요. 어디서 멈췄는지 법규 패널에서 보시겠어요?', actions: [law, flow, { label: '시스템 보기', artifact: 'system' }, later] }
  }
  if (verdictLabel(results.status, results.review?.code).includes('근거')) {
    const numbers = results.law && (results.law.bcr_pct !== null || results.law.far_pct !== null)
    return {
      text: numbers ? '법규 한계는 나왔지만 근거가 더 필요해요. 법규를 보시겠어요?' : '근거가 부족해 법규 한계를 확정하지 못했어요. 법규를 보시겠어요?',
      actions: [law, related, flow, later],
    }
  }
  return { text: '법규 검토가 끝났어요. 법규를 보시겠어요?', actions: [law, related, flow, later] }
}

/**
 * A question that is another agent's business: the Orchestrator says whose and, when the catalog
 * goal is open, offers to start it; when it is not, says so (fail closed, no guess).
 */
export function handoffLine(answer: AskAnswer, needed: readonly string[] = []): FeedInput {
  const { route, handoff } = answer
  const who = agentLabel(route.agent ?? ORCHESTRATOR)
  // The Orchestrator's own words to that agent (its ledger), shown as the instruction it would give.
  const said = route.instruction ? ` · ${who}에게: "${route.instruction}"` : ''
  if (!handoff) return { kind: 'error', agent: ORCHESTRATOR, text: `${who}의 일인데 아직 넘길 목표가 없어요` }
  if (handoff.available) {
    // The button says what will happen: owners the host has not got up are woken first ("켜고 시작").
    const label = needed.length ? `켜고 시작 (${needed.length}개)` : `${handoff.label} 시작`
    return {
      kind: 'prompt',
      agent: ORCHESTRATOR,
      text: `이건 ${who}의 일이에요${said} — ${handoff.label}을(를) 시작할까요?${needed.length ? ` (${needed.map(agentLabel).join(' · ')}은(는) 꺼져 있어 먼저 켜요)` : ''}`,
      actions: [{ label, command: { kind: 'start-review', goal: handoff.goal } }, { label: '나중에' }],
    }
  }
  const owners = handoff.owners.map(agentLabel).join(' → ')
  return { kind: 'progress', agent: ORCHESTRATOR, tone: 'warn', text: `이건 ${who}의 일이에요${said} (${handoff.label}${owners ? `: ${owners}` : ''}) — 이 목표는 아직 열리지 않았어요` }
}

/**
 * A question that belongs to a registered agent without a role module: the Orchestrator names it in the agent's
 * own card words, says what it would tell it, and offers to send the question on through the conversation
 * (where the Orchestrator's conversation calls the agent's skill) — no guessed skill call here.
 */
export function delegateLine(answer: AskAnswer): FeedInput {
  const { route, delegate, question } = answer
  const who = delegate?.label ?? agentLabel(route.agent ?? ORCHESTRATOR)
  if (!delegate) return { kind: 'error', agent: ORCHESTRATOR, text: `${who}의 일인데 그 에이전트를 찾지 못했어요` }
  const said = delegate.instruction ? ` · ${who}에게: "${delegate.instruction}"` : ''
  const skills = delegate.skills.map((skill) => skill.name)
  return {
    kind: 'prompt',
    agent: ORCHESTRATOR,
    text: `이건 ${who}의 일이에요${said}${delegate.description ? ` — ${delegate.description}` : ''}${delegate.available ? '' : ' (지금은 응답하지 않아요)'}`,
    ...(skills.length ? { card: { type: 'chips', items: skills } } : {}),
    actions: [{ label: '대화로 보내기', command: { kind: 'compose', draft: question } }, { label: '나중에' }],
  }
}

/** The Orchestrator answered the user itself (its ledger found the request satisfied): its words as its turn. */
export function orchestratorReplyLine(answer: AskAnswer): FeedInput {
  return { kind: 'progress', agent: ORCHESTRATOR, tone: 'ok', text: answer.route.instruction ?? answer.route.reason }
}

/** The router could not tell whose question it is: the Orchestrator asks, the roles are the answers. */
export function askRolePrompt(answer: AskAnswer): FeedInput {
  return {
    kind: 'prompt',
    agent: ORCHESTRATOR,
    text: `${answer.route.reason}. 누구에게 물을까요?`,
    actions: [...answer.route.choices.map((choice) => ({ label: choice.label, command: { kind: 'ask' as const, text: answer.question, role: choice.agent } })), { label: '나중에' }],
  }
}
