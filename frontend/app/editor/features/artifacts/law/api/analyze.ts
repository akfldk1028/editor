/**
 * `POST /api/v1/land/analyze` for one parcel. The response types come from `features/land-map`
 * (a legacy page feature this slice reuses read-only; to be folded in later); the fields the
 * `/land` page never read (assessment, program, zone overlap) are typed here.
 */
import type { LandAnalysisResult, ZoneInfo } from '../../../land-map/lib/types'

export interface CoverageSource { name: string; effective_date?: string; url?: string }

export interface Assessment {
  status: string
  permit_compliance_verified: boolean
  scope?: string
  municipal_coverage?: {
    status?: string
    assessment_date?: string
    sources?: CoverageSource[]
    missing_evidence?: string[]
    limitations?: string[]
  }
  missing_evidence?: string[]
}

/** `zone_info` as the backend sends it: caps are null until the ordinance evidence is complete. */
export interface LawZoneInfo extends Omit<ZoneInfo, 'bcr_limit' | 'far_limit'> {
  bcr_limit: number | null
  far_limit: number | null
  matched?: number
  unmatched?: string[]
  zone_areas_m2?: Record<string, number>
  overlap?: { article?: string; capacity_method?: string }
}

export interface LawAnalysis extends Omit<LandAnalysisResult, 'zone_info'> {
  zone_info: LawZoneInfo | null
  program?: { building_type: string; floor_area_m2: number | null; assessment_date: string }
  assessment?: Assessment
  storage?: { saved: boolean; analysis_id: string | null }
}

/** The 조건 the viewer sets; empty values are left out of the request. */
export interface AnalyzeOptions {
  buildingType?: string
  floorAreaM2?: number | null
  assessmentDate?: string
}

const base = () => process.env.NEXT_PUBLIC_BASE_PATH || ''

export async function analyzeSite(pnu: string, options: AnalyzeOptions, signal?: AbortSignal): Promise<LawAnalysis> {
  const body: Record<string, unknown> = { input: pnu, input_type: 'pnu' }
  if (options.buildingType) body.building_type = options.buildingType
  if (options.floorAreaM2 != null && options.floorAreaM2 > 0) body.floor_area_m2 = options.floorAreaM2
  if (options.assessmentDate) body.assessment_date = options.assessmentDate
  const response = await fetch(`${base()}/api/v1/land/analyze`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  })
  if (!response.ok) {
    console.error(`[law] analyze failed (${response.status})`, await response.text().catch(() => ''))
    throw new Error(response.status >= 500
      ? '분석 서버가 응답하지 않습니다. 잠시 후 다시 시도해 주세요.'
      : `분석 요청을 처리하지 못했습니다 (${response.status}).`)
  }
  return response.json() as Promise<LawAnalysis>
}
