/** Feed lines from run snapshots and parsed results. Pure: the hooks decide when to post. */
import type { FeedInput } from './feed'
import { agentForTool, agentLabel, evidenceLabel, shortEvidence, stateLabel, toolLabel, traceLabel, verdictLabel } from './labels'
import type { Communication, OrchestratorConnection, RunResults, RunSummary } from './types'

const fmt = (value: number, digits: number) => value.toLocaleString('ko-KR', { maximumFractionDigits: digits })

export interface SelectedSite {
  label: string
  parcels: readonly unknown[]
  total_area_m2: number | null
}

/** "대지 선택: 경기도 의정부시 산곡동 684-1 (1필지, 2,499.98㎡)" */
export function selectedLine(site: SelectedSite): string {
  const area = site.total_area_m2 === null ? '' : `, ${fmt(site.total_area_m2, 2)}㎡`
  return `대지 선택: ${site.label} (${site.parcels.length}필지${area})`
}

export function connectionLine(connection: OrchestratorConnection): FeedInput {
  if (connection.state === 'up') return { kind: 'system', text: `오케스트레이터 연결됨 · 에이전트 ${connection.agentsUp}/${connection.agentsTotal}` }
  return {
    kind: 'error',
    text: connection.state === 'invalid' ? '오케스트레이터 응답 형식이 맞지 않아요' : '오케스트레이터에 연결할 수 없어요',
    actions: [{ label: '시스템 보기', artifact: 'system' }],
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

/** "대지 · 대지 사실 확인: 근거 부족 (5/8 사실)" — one per step whose state is new or changed since `prev`. */
export function stepChanges(prev: Pick<RunSummary, 'communications'> | null, next: Pick<RunSummary, 'communications'>): { key: string; text: string }[] {
  const before = new Map((prev?.communications ?? []).map((comm) => [comm.tool, stepState(comm)]))
  const lines: { key: string; text: string }[] = []
  for (const comm of next.communications) {
    const state = stepState(comm)
    if (before.get(comm.tool) === state) continue
    const response = parsed(comm.response_text)
    const facts = typeof response.summary === 'string' ? response.summary.match(/(\d+)\s*\/\s*(\d+)\s*site facts/) : null
    const detail = facts ? ` (${facts[1]}/${facts[2]} 사실)` : typeof response.code === 'string' && state === 'failed' ? ` — ${evidenceLabel(response.code)}` : ''
    lines.push({ key: `${comm.tool}:${state}`, text: `${agentLabel(agentForTool(comm.tool, comm.agent))} · ${toolLabel(comm.tool)}: ${stateLabel(state)}${detail}` })
  }
  return lines
}

/** "법규: 대지 2,499.7㎡ · 건폐 59.92% · 용적 249.67% · 5층" — null until Law's numbers arrive. */
export function lawLine(results: RunResults): string | null {
  const law = results.law
  if (!law) return null
  const parts = [
    law.site_area_m2 !== null ? `대지 ${fmt(law.site_area_m2, 1)}㎡` : null,
    law.bcr_pct !== null ? `건폐 ${fmt(law.bcr_pct, 2)}%` : null,
    law.far_pct !== null ? `용적 ${fmt(law.far_pct, 2)}%` : null,
    law.max_floors !== null ? `${law.max_floors}층` : null,
  ].filter((part): part is string => part !== null)
  return parts.length ? `법규: ${parts.join(' · ')}` : null
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
