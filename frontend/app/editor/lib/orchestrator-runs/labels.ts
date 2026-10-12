/** Korean words for run statuses, agents, tools, step states and missing-evidence codes. Pure. */
import { agentSpec, canonicalAgent, toolOwner, toolSpecLabel } from '@/lib/agents'

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

/** Agents go by their network names in English (user, 2026-10-08); the table is `agents.ts`. */
export const agentLabel = (agent: string | null | undefined): string => (agent ? agentSpec(agent)?.name ?? agent : '—')

/** The agent that owns a tool, for a step record that has not named its agent yet (a running step). */
export function agentForTool(tool: string | null | undefined, agent?: string | null): string | null {
  if (agent) return canonicalAgent(agent)
  if (!tool) return null
  return toolOwner(tool)
}

export function toolLabel(tool: string | null | undefined): string {
  if (!tool) return '—'
  if (tool.endsWith('_health')) return `${agentLabel(toolOwner(tool) ?? tool.slice(0, -'_health'.length))} 상태 확인`
  return toolSpecLabel(tool) ?? tool
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
  complete_design_applicability_and_permit_checks: '설계 적용성·허가 검토 미완료',
  missing_ordinance_snapshot: '조례 스냅숏 없음',
}

/** A missing-evidence code in Korean; a `finding: sentence` entry keeps the sentence; unknown codes stay. */
export function evidenceLabel(code: string): string {
  if (EVIDENCE[code]) return EVIDENCE[code]!
  const [kind, value] = code.split(':', 2)
  if (kind === 'unresolved_zoning') return `용도 구분 미확인: ${value}`
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
  [/^re-run:\s*(\S+)/i, '$1 재실행'],
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

/** The Site Agent's eight facts (`sitecontextagent/facts.py` SITE_KEYS), in its order; the first three block siting. */
export const SITE_FACTS: readonly { key: string; code: string; label: string; critical: boolean }[] = [
  { key: 'site.boundary', code: 'SITE-BOUNDARY', label: '대지 경계', critical: true },
  { key: 'site.roads', code: 'SITE-ROADS', label: '접도 도로', critical: true },
  { key: 'site.access', code: 'SITE-ACCESS', label: '출입구·접근', critical: false },
  { key: 'site.north', code: 'SITE-NORTH', label: '정북·진북', critical: true },
  { key: 'site.terrain', code: 'SITE-TERRAIN', label: '지형·표고', critical: false },
  { key: 'site.utilities', code: 'SITE-UTILITIES', label: '설비 인입', critical: false },
  { key: 'site.hazards', code: 'SITE-HAZARDS', label: '재해 위험', critical: false },
  { key: 'site.context', code: 'SITE-CONTEXT', label: '주변 맥락', critical: false },
]

/** Site's confidence words (`facts.py` CONFIDENCE). */
export function confidenceLabel(confidence: string | null | undefined): string {
  switch (confidence) {
    case 'measured':
      return '공식 자료'
    case 'derived':
      return '산출'
    case 'estimated':
      return '추정'
    case 'unknown':
      return '미확인'
    default:
      return confidence || '—'
  }
}

/** Revision's finding categories (`facts.py`, `district_plan_review.py`). */
const CATEGORIES: Record<string, string> = {
  site_fact_missing: '대지 사실 누락',
  district_assessment_input: '지구단위 검토 입력 필요',
  district_source_evidence: '지구단위 출처 근거',
  district_legal_evidence: '지구단위 법적 근거',
}

export const categoryLabel = (category: string | null | undefined): string => (category ? CATEGORIES[category] ?? category : '—')

/** Law's height status word. */
export function heightLabel(status: string | null | undefined, limitM: number | null | undefined): string {
  if (limitM !== null && limitM !== undefined) return `${limitM} m`
  if (status === 'no_height_overlay') return '높이 지구 없음'
  return status ? status : '—'
}

/** Law's ordinance snapshot limitations. */
const LIMITATIONS: Record<string, string> = {
  snapshot_does_not_certify_amendment_completeness: '스냅샷은 개정 완전성을 보증하지 않음',
  parcel_plan_conditions_and_transitional_rules_require_review: '필지별 계획 조건·경과 규정은 별도 검토 필요',
}

export const limitationLabel = (code: string): string => LIMITATIONS[code] ?? code

/** Law's frontage evidence grade. */
export function frontageLabel(grade: string | null | undefined): string | null {
  if (!grade) return null
  if (grade === 'inferred_not_road_verified') return '접도 방향 추정 (도로 미검증)'
  if (grade === 'road_verified') return '접도 방향 도로 확인'
  return grade
}

/** The run's terminal verdict for a feed line. */
export function verdictLabel(status: string, reviewCode: string | null | undefined): string {
  if (status === 'blocked' || status === 'needs_evidence' || reviewCode === 'needs_user_input') return '보류 — 근거 보충 필요'
  return statusLabel(status)
}
