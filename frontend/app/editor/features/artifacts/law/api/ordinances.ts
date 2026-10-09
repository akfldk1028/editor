/**
 * The ordinances that can bind the selected parcel on the assessment date, `POST /api/v1/platform/ordinances`:
 * the backend resolves the parcel's governments from its registry address, walks every page of the official
 * law.go.kr ordinance search for each government × topic (the ordinances the review cites + the statutory
 * delegations), keeps only records issued by those governments, and picks the edition in force on the date.
 * What comes back is a list of sources to read with their official URL — never applicability, never a body.
 */
import type { ReferenceSite } from './reference'

export interface OrdinanceRefInput { instrument: string; item_id?: string; title?: string; article?: string | null; status?: string }

export interface OrdinanceLevel {
  level: 'sido' | 'sigungu'
  name: string
  issuer: string
  code?: string
  check?: 'ordinance_snapshot_match' | 'address_only' | 'conflict'
  source?: string
  snapshot_name?: string
}

export interface OrdinanceJurisdiction {
  address: string | null
  status: 'resolved' | 'unresolved' | 'conflict'
  reason: string | null
  levels: OrdinanceLevel[]
  notes: string[]
}

export interface OrdinanceQuery {
  level: string; issuer: string; query: string; edition_set: 'current' | 'history'
  pages?: number; total?: number; complete?: boolean; error?: string | null
}

export interface OrdinanceReviewRef { item_id: string | null; title: string | null; article: string | null; status: string | null; match: 'exact' | 'generic_name' }

export interface DiscoveredOrdinance {
  name: string
  kind: string | null
  ordinance_id: string | null
  edition_id: string
  effective_date: string | null
  promulgated: string | null
  promulgation_no: string | null
  revision: string | null
  issuer: string
  detail_url: string | null
  level: 'sido' | 'sigungu'
  url: string
  editions_seen: number
  future_editions: { edition_id: string; effective_date: string | null }[]
  status: { jurisdiction: 'verified'; edition: 'dated' | 'history_only'; body: 'not_fetched'; in_force: 'current' | 'unknown'; relevance: 'exact' | 'topic' }
  review_refs: OrdinanceReviewRef[]
  topics: string[]
}

export interface OrdinanceDiscovery {
  pnu: string
  assessment_date: string
  retrieved_at?: string
  source?: string
  error?: string
  jurisdiction: OrdinanceJurisdiction
  topics: { topic: string; from: string[] }[]
  search: { queries: OrdinanceQuery[]; complete: boolean; other_results: number; errors?: string[] }
  ordinances: DiscoveredOrdinance[]
  historical?: DiscoveredOrdinance[]
  excluded: { name: string; issuer: string; reason: string; first_effective_date?: string | null }[]
  excluded_total?: number
  coverage_complete: false
  coverage_note?: string
}

export interface OrdinanceAnnex { number: string | null; title: string; kind: string | null; file_kind: string | null; file_url: string | null; content: string | null }

/** One edition's whole text from the official record (`POST /api/v1/platform/ordinances/body`), verified as that edition. */
export interface OrdinanceBody {
  ordinance: { name: string; ordinance_id: string | null; edition_id: string; effective_date: string | null; promulgated: string | null; promulgation_no: string | null; issuer: string | null; url: string }
  assessment_date: string
  articles: { article: string; title: string; content: string; heading: boolean }[]
  annexes: OrdinanceAnnex[]
  supplement: { promulgated: string | null; no: string | null; content: string | null }
  status: { identity: 'body_verified'; applicability: 'unknown' }
  source: string
  retrieved_at: string
}

const base = () => process.env.NEXT_PUBLIC_BASE_PATH || ''

export async function fetchOrdinanceBody(edition: { name: string; edition_id: string; assessment_date: string }, signal?: AbortSignal): Promise<OrdinanceBody> {
  const response = await fetch(`${base()}/api/v1/platform/ordinances/body`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal, body: JSON.stringify(edition),
  })
  if (!response.ok) throw new Error(`조례 전문을 받지 못했습니다 (${response.status}). 공식 원문 링크로 확인해 주세요.`)
  const data = (await response.json()) as OrdinanceBody & { error?: string; reason?: string }
  if (data.error) throw new Error(`조례 전문을 받지 못했습니다 (${data.reason ?? data.error}). 공식 원문 링크로 확인해 주세요.`)
  if (!Array.isArray(data.articles) || !data.ordinance) throw new Error('조례 전문 응답의 형식이 맞지 않습니다.')
  return data
}

export async function discoverOrdinances(site: ReferenceSite, refs: OrdinanceRefInput[], signal?: AbortSignal): Promise<OrdinanceDiscovery> {
  const response = await fetch(`${base()}/api/v1/platform/ordinances`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ pnu: site.pnu, assessment_date: site.assessmentDate, refs }),
  })
  if (!response.ok) {
    throw new Error(response.status >= 500 ? `관할 조례 목록을 받지 못했습니다 (${response.status}). 조례가 없다는 뜻은 아닙니다.` : `관할 조례 요청을 처리하지 못했습니다 (${response.status}).`)
  }
  const data = (await response.json()) as OrdinanceDiscovery
  if (!data || typeof data !== 'object' || !Array.isArray(data.ordinances) || !data.jurisdiction) throw new Error('관할 조례 응답의 형식이 맞지 않습니다.')
  return data
}
