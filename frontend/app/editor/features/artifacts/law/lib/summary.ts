/** Pure derivations for the 요약 tab and the header counts. */
import { CORE_REGULATIONS } from '../../../land-map/lib/constants'
import type { Assessment, LawAnalysis } from '../api/analyze'

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)
const str = (value: unknown): string | null => (typeof value === 'string' && value ? value : null)
const pct = (value: number) => value.toLocaleString('ko-KR', { maximumFractionDigits: 1 })

export const formatArea = (value: number | null | undefined) =>
  value == null ? '—' : `${value.toLocaleString('ko-KR', { maximumFractionDigits: 2 })} ㎡`

export const formatWon = (value: number | null | undefined) =>
  value == null ? '—' : `${value.toLocaleString('ko-KR')} 원/㎡`

/** 건폐율/용적률 cap: the ordinance limit when known, else the statutory ceiling as context. */
export interface Cap { limit: number | null; ceiling: number | null; status: string | null; article: string }

export function capOf(item: unknown): Cap {
  const record = (item ?? {}) as Record<string, unknown>
  return { limit: num(record.limit_pct), ceiling: num(record.national_ceiling_pct), status: str(record.status), article: str(record.article) ?? '' }
}

/** "60%" with no note; or "미확정" with the ceiling as a note — never the ceiling as the answer. */
export function formatCap(cap: Cap): { value: string; note: string | null } {
  if (cap.limit !== null) return { value: `${pct(cap.limit)}%`, note: null }
  const ceiling = cap.ceiling !== null ? `법정 상한 ${pct(cap.ceiling)}% 이하 · ` : ''
  return { value: '미확정', note: `${ceiling}조례 증거 확인 필요` }
}

/** What a cap stat shows: value, the note under it, the basis line, and whether it is a warning. */
export interface CapStat { value: string; note: string | null; basis: string; warn: boolean }

/**
 * The Law Agent's cap (`law_parcel_limits`: district policy or ordinance, area-weighted over split
 * zoning) is the answer when it has one; the editor calculator's own verdict stays under it as a
 * note when it differs (미확정 — it does not weight across zones or settle unmatched districts).
 * Without the Law Agent's number the calculator's own result shows as before.
 */
export function capStat(cap: Cap, agentPct: number | null, agentArticle: string | null, policyId: string | null): CapStat {
  if (agentPct === null) {
    const own = formatCap(cap)
    return { value: own.value, note: own.note, basis: cap.article, warn: own.note !== null }
  }
  const basis = ['Law Agent', agentArticle ?? (cap.article || null), policyId ? `지구단위 정책 ${policyId}` : null].filter((part): part is string => Boolean(part)).join(' · ')
  const own = formatCap(cap)
  const differs = cap.limit !== null && Math.abs(cap.limit - agentPct) > 0.05
  const note = cap.limit === null ? `에디터 계산기: ${own.value} — ${own.note}` : differs ? `에디터 계산기: ${own.value}` : null
  return { value: `${pct(agentPct)}%`, note, basis, warn: false }
}

export type Tone = 'ok' | 'warn' | 'muted'
export interface AssessmentBadge { label: string; tone: Tone; detail: string[] }

const STATUS_LABEL: Record<string, string> = {
  verified: '검증됨', complete: '완료', partial: '일부 산정', needs_evidence: '증거 부족', needs_review: '검토 필요',
}

const formatYmd = (value: string) => (/^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}` : value)

const MISSING_LABEL: Record<string, string> = {
  complete_design_applicability_and_permit_checks: '설계 적용성·허가 검토 미완료',
  missing_ordinance_snapshot: '조례 스냅숏 없음',
}

/** `kind:value` codes from the backend; unknown codes stay as they are rather than vanish. */
function describeMissing(code: string): string {
  const [kind, value] = code.split(':', 2)
  if (kind === 'unresolved_zoning') return `미인식 용도지역: ${value}`
  return MISSING_LABEL[code] ?? code
}

/** The 심사 상태 badge: status word, tone, and the lines under it (scope, ordinance edition, missing evidence). */
export function assessmentBadge(assessment: Assessment | undefined): AssessmentBadge {
  if (!assessment) return { label: '심사 정보 없음', tone: 'muted', detail: [] }
  const detail: string[] = []
  if (!assessment.permit_compliance_verified) detail.push('허가 적합성 미검증 — 규제 조회와 일부 산정 범위')
  for (const source of assessment.municipal_coverage?.sources ?? []) {
    detail.push(`${source.name}${source.effective_date ? ` (시행 ${formatYmd(source.effective_date)})` : ''}`)
  }
  const missing = new Set([...(assessment.missing_evidence ?? []), ...(assessment.municipal_coverage?.missing_evidence ?? [])])
  for (const code of missing) detail.push(describeMissing(code))
  return {
    label: STATUS_LABEL[assessment.status] ?? assessment.status,
    tone: assessment.permit_compliance_verified ? 'ok' : 'warn',
    detail,
  }
}

export interface ZoneArea { zone: string; areaM2: number }

export interface Summary {
  pnu: string
  /** 용도지역 the engine matched to a cap table. */
  zones: string[]
  /** Districts and other designations it did not match (shown, never silently dropped). */
  otherZones: string[]
  /** Split-zoning areas, largest first. */
  zoneAreas: ZoneArea[]
  overlapArticle: string | null
  bcr: Cap
  far: Cap
  areaM2: number | null
  landCategory: string | null
  officialPrice: number | null
  restrictions: string[]
  assessment: AssessmentBadge
  assessmentDate: string | null
}

export function summarize(analysis: LawAnalysis): Summary {
  const zone = analysis.zone_info
  const land = analysis.land_info
  const reg = analysis.regulations ?? {}
  const pnu = typeof analysis.pnu === 'string' ? analysis.pnu : analysis.pnu?.pnu ?? ''
  const zoneAreas = Object.entries(zone?.zone_areas_m2 ?? {})
    .map(([name, area]) => ({ zone: name, areaM2: area }))
    .sort((a, b) => b.areaM2 - a.areaM2)
  return {
    pnu,
    zones: zone?.zones ?? land?.zones ?? [],
    otherZones: zone?.unmatched ?? [],
    zoneAreas,
    overlapArticle: zoneAreas.length > 1 ? str(zone?.overlap?.article) : null,
    bcr: capOf(reg.bcr),
    far: capOf(reg.far),
    areaM2: num(land?.land_area_m2),
    landCategory: str(land?.land_use_situation) ?? str(typeof analysis.pnu === 'object' ? analysis.pnu?.land_type_name : null),
    officialPrice: num(land?.official_land_price),
    restrictions: analysis.restrictions ?? [],
    assessment: assessmentBadge(analysis.assessment),
    assessmentDate: str(analysis.program?.assessment_date) ?? str(analysis.assessment?.municipal_coverage?.assessment_date),
  }
}

/** Same count the /land panel shows: core cards present + extended + 지역·지구 overlays. */
export function countRegulations(analysis: LawAnalysis): number {
  const reg = analysis.regulations
  const core = Object.keys(CORE_REGULATIONS).filter((key) => reg?.[key]).length
  const extended = reg?.extended ? Object.keys(reg.extended).length : 0
  return core + extended + (analysis.overlay_regulations?.length ?? 0)
}

export const countArticles = (analysis: LawAnalysis): number =>
  analysis.law_articles?.total_count || analysis.law_articles?.articles?.length || 0

/** "684-1" from an address (or, failing that, from the PNU's 본번-부번). */
export function lotLabel(address: string, pnu: string): string {
  const tail = address.trim().match(/(산\s*)?\d+(-\d+)?$/)
  if (tail) return tail[0].replace(/\s+/g, '')
  const main = Number(pnu.slice(11, 15))
  const sub = Number(pnu.slice(15, 19))
  return `${pnu[10] === '2' ? '산' : ''}${main}${sub ? `-${sub}` : ''}`
}
