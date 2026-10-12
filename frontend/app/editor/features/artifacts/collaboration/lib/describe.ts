import { actionLabel, agentLabel, evidenceLabel, stateLabel, toolLabel } from '@/lib/orchestrator-runs/labels'

import type { CollaborationMessage } from './transcript'

/** A message in the user's words: one headline, a few lines, and the record itself for the curious. */
export interface Described {
  headline: string
  lines: string[]
  raw: string | null
  truncated: boolean
}

/** Why a step ended the way it did, for the codes the Orchestrator and its adapters emit; unknown codes fall back to `evidenceLabel`. */
export const CODE_NOTES: Record<string, string> = {
  site_patch_out_of_scope: 'Site의 답에 오케스트레이터가 모르는 항목이 있어 답 전체를 받지 않음',
  site_resolve_failed: 'Site가 대지 사실을 확인하지 못함',
  invalid_site_contract: 'Site 답의 형식이 계약과 다름',
  needs_user_input: '사용자 입력이 필요함',
  execution_error: '실행 중 오류',
  connection_failed: '에이전트에 연결하지 못함',
  agent_unauthorized: '에이전트가 호출을 거절함(인증)',
}

export const codeNote = (code: string): string => CODE_NOTES[code] ?? evidenceLabel(code)

/** Request arguments in the user's words; internal plumbing keys are not shown. */
const ARG_LABELS: Record<string, string> = { pnu: '대지', building_type: '용도', assessment_date: '기준일', goal: '목표', query: '질문' }
const HIDDEN_ARGS = new Set(['project', 'branch', 'idempotency_key', 'run_id', 'task_id', 'context_id', 'facts', 'source_versions'])

/** Site fact keys as the user knows them. */
const FACT_LABELS: Record<string, string> = {
  'site.boundary': '경계', 'site.roads': '도로', 'site.north': '정북', 'site.terrain': '지형', 'site.zoning': '용도지역',
  'site.district_plan': '지구단위계획', 'site.access': '접근', 'site.hazards': '재해', 'site.utilities': '설비', 'site.context': '주변',
}
const factLabel = (key: string) => FACT_LABELS[key] ?? key.replace(/^site\./, '')

const MAX_LINES = 8
const PREVIEW_CHARS = 200

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)

function parse(text: string): unknown | undefined {
  try { return JSON.parse(text) } catch { return undefined }
}

/** The record for the details view: pretty JSON with coordinate arrays elided, or the text as recorded. */
function rawOf(text: string, value: unknown): string {
  if (value === undefined) return text
  return JSON.stringify(value, (key, item) => (key === 'coordinates' ? '[좌표 생략]' : item), 2)
}

const short = (value: unknown): string => {
  if (value === null || value === undefined) return '—'
  if (typeof value !== 'object') return String(value)
  if (Array.isArray(value)) return value.every((item) => typeof item !== 'object') ? value.map(String).join(', ') : `${value.length}개`
  return '(상세)'
}

function requestLines(args: Record<string, unknown>): string[] {
  const lines: string[] = []
  if (Array.isArray(args.parcels) && args.parcels.length > 1) lines.push(`필지 ${args.parcels.length}개`)
  if (isRecord(args.site_evidence)) lines.push('대지 근거를 함께 보냄')
  if (Array.isArray(args.open_issues) && args.open_issues.length) lines.push(`열린 이슈 ${args.open_issues.length}개`)
  let others = 0
  for (const [key, value] of Object.entries(args)) {
    if (HIDDEN_ARGS.has(key) || key === 'parcels' || key === 'site_evidence' || key === 'open_issues') continue
    if (ARG_LABELS[key]) lines.push(`${ARG_LABELS[key]} ${short(value)}`)
    else others += 1
  }
  // The Orchestrator's own bookkeeping (budgets, owners, dirty nodes …) stays in the record, not in the sentence.
  if (others) lines.push(`그 밖의 전달 항목 ${others}개 — 기록 원문에`)
  return lines
}

/** What can still be read from a record the 8,000-character cap cut mid-JSON: the headline fields and which facts it carried. */
function salvageLines(text: string): string[] {
  const lines: string[] = []
  const field = (name: string) => new RegExp(`"${name}"\\s*:\\s*"([^"]*)"`).exec(text)?.[1]
  const summary = field('summary')
  const code = field('code')
  if (summary) lines.push(summary)
  if (code) lines.push(codeNote(code))
  return lines
}

function responseLines(body: Record<string, unknown>): string[] {
  const lines: string[] = []
  if (typeof body.summary === 'string' && body.summary) lines.push(body.summary)
  if (typeof body.code === 'string' && body.code) lines.push(codeNote(body.code))
  if (Array.isArray(body.out_of_scope) && body.out_of_scope.length) lines.push(`오케스트레이터가 받지 않은 항목: ${body.out_of_scope.map((key) => factLabel(String(key))).join(', ')}`)
  for (const key of ['reason', 'error'] as const) if (typeof body[key] === 'string' && body[key]) lines.push(String(body[key]))
  if (isRecord(body.state_patch)) {
    const facts = Object.entries(body.state_patch).map(([key, fact]) => {
      const summary = isRecord(fact) && typeof fact.summary === 'string' && fact.summary ? `(${fact.summary})` : ''
      return factLabel(key) + summary
    })
    if (facts.length) lines.push(`확인된 사실 ${facts.length}개: ${facts.join(' · ')}`)
  }
  if (Array.isArray(body.missing_evidence) && body.missing_evidence.length) lines.push(`부족한 근거: ${body.missing_evidence.map((code) => evidenceLabel(String(code))).join(', ')}`)
  if (Array.isArray(body.actions)) {
    for (const action of body.actions) {
      if (!isRecord(action)) continue
      const evidence = Array.isArray(action.evidence) ? action.evidence.map(String).join(' · ') : ''
      const who = typeof action.recommended_action === 'string' ? ` → ${actionLabel(action.recommended_action)}` : ''
      if (evidence || who) lines.push(`${evidence}${who}`.trim())
    }
  }
  if (isRecord(body.payload) && typeof body.payload.summary === 'string' && !lines.includes(body.payload.summary)) lines.push(body.payload.summary)
  return lines
}

export function describeMessage(message: CollaborationMessage): Described {
  const who = `${agentLabel(message.from)} → ${agentLabel(message.to)}`
  const value = parse(message.text)
  const raw = rawOf(message.text, value)
  if (message.direction === 'request') {
    const lines = isRecord(value) ? requestLines(value) : [message.text.slice(0, PREVIEW_CHARS)]
    return { headline: `${who} · ${toolLabel(message.tool)} 요청`, lines: lines.slice(0, MAX_LINES), raw, truncated: message.truncated }
  }
  const headline = `${who} · ${toolLabel(message.tool)} · ${stateLabel(message.state)}`
  if (!isRecord(value)) {
    const salvaged = message.truncated ? salvageLines(message.text) : []
    const lines = salvaged.length ? [...salvaged, '기록이 잘렸어요 — 긴 답은 8,000자까지만 남아요'] : [message.truncated ? `${message.text.slice(0, PREVIEW_CHARS)} … 기록이 잘렸어요` : message.text.slice(0, PREVIEW_CHARS)]
    return { headline, lines, raw, truncated: message.truncated }
  }
  const lines = responseLines(value)
  if (message.truncated) lines.push('기록이 잘렸어요 — 긴 답은 8,000자까지만 남아요')
  return { headline, lines: lines.slice(0, MAX_LINES), raw, truncated: message.truncated }
}
