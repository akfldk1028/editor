/**
 * The Law Agent's analysis of one parcel, `POST /api/v1/platform/law-analysis` (the backend asks
 * `law_land_analyze` for the regulations, lines and articles and `law_parcel_limits` for the caps over
 * A2A). The analysis types come from `features/land-map` (a legacy page feature this slice reuses
 * read-only; to be folded in later); the fields the `/land` page never read are typed here.
 */
import type { LandAnalysisAnswer } from '@/lib/orchestrator-runs/types'
import { ensureAgents } from '@/lib/orchestrator-runs/api'
import { RUN_LEASE_S } from '@/lib/goals/activation'

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
  /** The exclusive zone split behind the areas and what it excluded as boundary tolerance (disclosed). */
  zone_split?: { notes?: string[]; excluded_slivers?: unknown[]; removed_zones?: string[]; north_neighbour_zone?: string | null } | null
}

/** One ordinance as the model read it from the official text (backend `ordinance_reading`): verified items only. */
export interface OrdinanceReadingResult {
  kind: string
  label?: string
  ordinance: { name: string; edition_id: string; effective_date: string | null; url: string | null }
  items: Record<string, { value: number | null; unit: string | null; by_scope: { scope: string; value: number | null; text?: string | null }[]; article: string; quote: string | null; note?: string | null }>
  dropped?: string[]
  reason?: string
}

export interface LawAnalysis extends Omit<LandAnalysisResult, 'zone_info'> {
  zone_info: LawZoneInfo | null
  /** What the jurisdiction's ordinances decide, by kind (건축·도시계획·주차장), as the model read them; null when unread. */
  ordinance_reading?: Record<string, OrdinanceReadingResult | null> | null
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

/** The Law Agent's answer: the whole analysis for the tabs, plus the caps and the conversation's summary. */
export interface LawAgentAnalysis extends LandAnalysisAnswer {
  analysis: LawAnalysis
}

export class AnalyzeError extends Error {
  constructor(message: string, readonly status: number | null) {
    super(message)
  }
}

const base = () => process.env.NEXT_PUBLIC_BASE_PATH || ''

export async function analyzeSite(pnu: string, options: AnalyzeOptions, signal?: AbortSignal): Promise<LawAgentAnalysis> {
  try {
    const ready = await ensureAgents(['law'], RUN_LEASE_S, signal)
    signal?.throwIfAborted()
    if (ready.failed.length || !ready.up.includes('law')) throw new Error('law_not_ready')
  } catch {
    signal?.throwIfAborted()
    throw new AnalyzeError('Law Agent를 시작하지 못했어요. 잠시 후 다시 분석해 주세요.', 503)
  }
  const body: Record<string, unknown> = { pnu }
  if (options.buildingType) body.building_type = options.buildingType
  if (options.floorAreaM2 != null && options.floorAreaM2 > 0) body.floor_area_m2 = options.floorAreaM2
  if (options.assessmentDate) body.assessment_date = options.assessmentDate
  const response = await fetch(`${base()}/api/v1/platform/law-analysis`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  })
  if (!response.ok) {
    console.error(`[law] analyze failed (${response.status})`, await response.text().catch(() => ''))
    throw new AnalyzeError(
      response.status === 503 ? 'Law Agent에 연결할 수 없어요 — 켜진 뒤 다시 분석해 주세요.'
        : response.status >= 500 ? 'Law Agent가 분석을 마치지 못했어요. 잠시 후 다시 시도해 주세요.'
          : `분석 요청을 처리하지 못했습니다 (${response.status}).`,
      response.status,
    )
  }
  return response.json() as Promise<LawAgentAnalysis>
}
