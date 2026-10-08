/** Korean words for run statuses, agents, tools, step states and missing-evidence codes. Pure. */

/** The run page's open statuses; anything else is terminal (RunPage polls on these three too). */
const OPEN = new Set(['queued', 'running', 'queued_input'])
export const isTerminal = (status: string) => !OPEN.has(status)

export function statusLabel(status: string): string {
  switch (status) {
    case 'queued':
      return '대기'
    case 'running':
      return '진행 중'
    case 'queued_input':
      return '입력 대기'
    case 'completed':
    case 'succeeded':
    case 'done':
      return '완료'
    case 'blocked':
    case 'needs_evidence':
      return '보류 — 근거 보충 필요'
    case 'failed':
    case 'error':
    case 'cancelled':
    case 'canceled':
    case 'rejected':
      return '실패'
    default:
      return status
  }
}

/** The card shows the first 8 hex of the 32-hex W3C trace id (and of a run id); the copy button carries the whole id. */
export const traceLabel = (id: string) => id.slice(0, 8)

const AGENTS: Record<string, string> = {
  site_context: '대지',
  'site-context': '대지',
  law: '법규',
  revision: '검토 조정',
  masterplan: '배치',
  mass: '매스',
  kmass: 'K매스',
  program: '프로그램',
  requirement: '요구사항',
  design_intent: '설계 의도',
  'design-intent': '설계 의도',
  elevation: '지반·표고',
  plan: '평면',
  systems: '설비',
  domain_expert: '전문 검토',
  'domain-expert': '전문 검토',
  interior: '인테리어',
  scene: '장면',
  orchestrator: '오케스트레이터',
  user: '사용자',
}

export const agentLabel = (agent: string | null | undefined): string => (agent ? AGENTS[agent] ?? agent : '—')

const TOOLS: Record<string, string> = {
  site_resolve: '대지 사실 확인',
  law_parcel_limits: '법규 한계',
  revision_triage: '재검토 판정',
}

const TOOL_OWNER: Record<string, string> = { site_resolve: 'site_context', law_parcel_limits: 'law', revision_triage: 'revision' }

/** The agent that owns a tool, for a step record that has not named its agent yet (a running step). */
export function agentForTool(tool: string | null | undefined, agent?: string | null): string | null {
  if (agent) return agent
  if (!tool) return null
  if (tool.endsWith('_health')) return tool.slice(0, -'_health'.length)
  return TOOL_OWNER[tool] ?? null
}

export function toolLabel(tool: string | null | undefined): string {
  if (!tool) return '—'
  if (tool.endsWith('_health')) return `${agentLabel(tool.slice(0, -'_health'.length))} 상태 확인`
  return TOOLS[tool] ?? tool
}

/** A communication's `state`, or a tool's own `status` word. */
export function stateLabel(state: string | null | undefined): string {
  switch (state) {
    case 'succeeded':
    case 'completed':
    case 'complete':
      return '성공'
    case 'needs_evidence':
    case 'partial':
      return '근거 부족'
    case 'needs_user_input':
      return '사용자 입력 필요'
    case 'failed':
    case 'error':
      return '실패'
    case 'running':
      return '진행 중'
    case 'queued':
    case 'pending':
      return '대기'
    case 'skipped':
      return '건너뜀'
    default:
      return state || '—'
  }
}

const EVIDENCE: Record<string, string> = {
  'SITE-ACCESS': '대지 접근(출입구·접도)',
  'SITE-HAZARDS': '재해 위험 정보',
  'SITE-UTILITIES': '설비 인입 정보',
  'SITE-BOUNDARY': '대지 경계',
  'SITE-ROADS': '접도 도로',
  assessment_date_required: '기준일 지정',
  district_effective_sources_unverified: '지구단위계획 시행 근거 미확인',
  district_applicability_unverified: '지구단위계획 적용 여부 미확인',
  district_complete_provisions_review_required: '지구단위계획 전체 조문 검토',
  regulation_receipt: '조례 영수증',
  parcels_not_contiguous: '필지가 서로 붙어 있지 않음',
}

/** A missing-evidence code in Korean; a `finding: sentence` entry keeps the sentence; unknown codes stay. */
export function evidenceLabel(code: string): string {
  if (EVIDENCE[code]) return EVIDENCE[code]!
  const [kind, value] = code.split(':', 2)
  if (kind === 'unresolved_zoning') return `미인식 용도지역: ${value}`
  if (value && kind?.startsWith('law.')) return actionLabel(value.trim())
  if (code.startsWith('law.district_review.')) return '지구단위계획 검토 (법규)'
  return code
}

/** Short Korean name for a feed line: "기준일, 대지 접근·재해·설비". */
const SHORT: Record<string, string> = {
  'SITE-ACCESS': '대지 접근',
  'SITE-HAZARDS': '재해',
  'SITE-UTILITIES': '설비',
  assessment_date_required: '기준일',
}

export function shortEvidence(codes: readonly string[]): string {
  const site = codes.filter((code) => code.startsWith('SITE-')).map((code) => SHORT[code] ?? code)
  const rest = codes.filter((code) => !code.startsWith('SITE-') && !code.includes(': ') && !code.startsWith('district_')).map((code) => SHORT[code] ?? evidenceLabel(code))
  const parts = [...new Set([...rest, ...(site.length ? [site.join('·')] : [])])]
  return parts.join(', ')
}

const ACTIONS: [RegExp, string][] = [
  [/^re-run:\s*(\S+)/i, '$1 에이전트 재실행'],
  [/Supply an explicit valid assessment date/i, '기준일을 명시해 주세요 — 법규 에이전트는 날짜·법령 판본을 대신 고르지 않아요'],
]

/** A recommended action in Korean when the sentence is known; else as the agent wrote it. */
export function actionLabel(action: string | null | undefined): string {
  if (!action) return '—'
  for (const [pattern, replacement] of ACTIONS) {
    const match = action.match(pattern)
    if (match) return replacement.replace('$1', agentLabel(match[1] ?? null))
  }
  return action
}

/** The run's terminal verdict for a feed line. */
export function verdictLabel(status: string, reviewCode: string | null | undefined): string {
  if (status === 'blocked' || status === 'needs_evidence' || reviewCode === 'needs_user_input') return '보류 — 근거 보충 필요'
  return statusLabel(status)
}
