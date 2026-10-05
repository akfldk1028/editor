const API_BASE = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land`

// --------------- Types ---------------

export interface PnuInfo {
  pnu: string
  sido: string
  sigungu: string
  eupmyeondong: string
  ri: string
  land_type: string
  main_number: string
  sub_number: string
  address?: string
  coordinate_x?: number
  coordinate_y?: number
}

export interface ZoneInfo {
  matched: number
  zones: string[]
  unmatched: string[]
}

export interface RegulationItem {
  limit_pct?: number | null
  limit_m?: number | null
  min_m?: number | null
  setback_m?: number | null
  multiplier?: number | null
  threshold_m2?: number | null
  min_pct?: number | null
  applies?: boolean
  required?: boolean
  direction?: string | null
  rules?: string[]
  rule?: string | null
  article: string
}

export interface ExtendedRegulationItem {
  name: string
  rule?: string
  article: string
  applies_when?: string
  allowed_summary?: string
  prohibited_summary?: string
  reference_table?: string
  min_frontage_m?: number
  min_area_m2?: number
  applies?: boolean
}

export interface RegulationsResponse {
  bcr: RegulationItem
  far: RegulationItem
  height: RegulationItem
  sunlight_setback: RegulationItem
  corner_cutoff: RegulationItem
  road_diagonal: RegulationItem
  building_line: RegulationItem
  adjacent_setback: RegulationItem
  parking: RegulationItem
  landscaping: RegulationItem
  extended?: Record<string, ExtendedRegulationItem>
}

export interface LandInfoResponse {
  success: boolean
  pnu: string
  land_area_m2?: number | null
  official_land_price?: number | null
  land_use_situation?: string | null
  zones?: string[]
  source: string
}

export interface LawArticle {
  hang_id: string
  content: string
  law_name: string
  law_type?: string
  article: string
  similarity?: number
  stages?: string[]
}

export interface LawArticlesResponse {
  articles: LawArticle[]
  total_count: number
  errors: string[]
}

export interface LandAnalyzeResponse {
  pnu: PnuInfo | null
  regulations: RegulationsResponse | null
  zone_info: ZoneInfo | null
  land_info: LandInfoResponse | null
  law_articles: LawArticlesResponse | null
  restrictions: string[]
  errors?: string[]
  warning?: string
}

export interface LandAnalyzeRequest {
  input: string
  input_type: 'pnu' | 'address' | 'raw'
  zones?: string[]
  include_law?: boolean
}

export interface LandResolveRequest {
  input: string
  input_type: 'pnu' | 'address'
}

export interface LandResolveResponse {
  valid?: boolean
  parsed?: Record<string, string>
  pnu?: string
  address?: string
  coordinate_x?: number
  coordinate_y?: number
  error?: string
}

export interface LandZone {
  zone_name: string
  bcr_default: number
  far_default: number
  category: string
}

export interface LandStats {
  total_queries: number
  avg_response_time_ms: number
  by_input_type: Array<{ input_type: string; count: number }>
  error_count: number
}

export interface LandZonesResponse {
  zones: LandZone[]
  count: number
}

// --------------- Fetch Helper ---------------

async function landFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers as Record<string, string>),
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : body?.error ?? `${res.status} ${res.statusText}`)
  }
  return res.json()
}

// --------------- Land API ---------------

export const landAPI = {
  analyze: (req: LandAnalyzeRequest) =>
    landFetch<LandAnalyzeResponse>('/analyze', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  resolve: (req: LandResolveRequest) =>
    landFetch<LandResolveResponse>('/resolve', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  zones: () => landFetch<LandZonesResponse>('/zones'),

  stats: () => landFetch<LandStats>('/stats'),
}
