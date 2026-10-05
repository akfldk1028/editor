/**
 * Land module — 타입 정의
 *
 * 모든 API 응답 타입은 여기서 정의. 컴포넌트/hook에서 import.
 * land-api-client.ts에는 타입을 두지 않음.
 */

// ---------------------------------------------------------------------------
// /land/analyze/ 응답
// ---------------------------------------------------------------------------

/** PNU 파싱 결과 (backend pnu_resolver.parse_pnu) */
export interface PnuInfo {
  pnu: string;
  sido: string;
  sigungu: string;
  eupmyeondong: string;
  ri: string;
  land_type: string;
  main_number: string;
  sub_number: string;
  land_type_name: string;
  address?: string;
  coordinate_x?: number;
  coordinate_y?: number;
}

/** 개별 규제 항목 (core: bcr, far, height 등) */
export interface RegulationItem {
  limit_pct?: number;
  limit_m?: number;
  setback_m?: number;
  min_m?: number;
  multiplier?: number;
  min_pct?: number;
  threshold_m2?: number;
  applies?: boolean;
  required?: boolean;
  direction?: string | null;
  rule?: string;
  rules?: string[];
  article?: string;
}

/** 확장 규제 항목 */
export interface ExtendedRegulationItem {
  name?: string;
  value?: string | number | null;
  limit?: number;
  unit?: string;
  applies?: boolean;
  article?: string;
  description?: string;
  rule?: string;
}

/** regulations 필드 전체 (flat dict: bcr, far, ... + extended) */
export interface Regulations {
  bcr?: RegulationItem;
  far?: RegulationItem;
  height?: RegulationItem;
  sunlight_setback?: RegulationItem;
  corner_cutoff?: RegulationItem;
  road_diagonal?: RegulationItem;
  building_line?: RegulationItem;
  adjacent_setback?: RegulationItem;
  parking?: RegulationItem;
  landscaping?: RegulationItem;
  extended?: Record<string, ExtendedRegulationItem>;
  [key: string]: RegulationItem | Record<string, ExtendedRegulationItem> | undefined;
}

/** zone_info 필드 */
export interface ZoneInfo {
  zones: string[];
  bcr_limit: number;
  far_limit: number;
}

/** land_info 필드 */
export interface LandInfo {
  success?: boolean;
  land_area_m2?: number;
  official_land_price?: number;
  land_use_situation?: string;
  source?: string;
  zones?: string[];
  [key: string]: unknown;
}

/** 법조항 한 건 */
export interface LawArticleItem {
  hang_id: string;
  content: string;
  law_name?: string;
  law_type?: string;
  article?: string;
  similarity?: number;
  stages?: string[];
}

/** law_articles 필드 */
export interface LawArticlesResult {
  articles?: LawArticleItem[];
  total_count?: number;
  errors?: string[];
}

/** 오버레이 규제 항목 (지구/구역/보호구역) */
export interface OverlayRegulation {
  name: string;
  raw_zone: string;
  category: string;
  constraint: string;
  article: string;
  description: string;
  values: Record<string, number>;
}

/** GeoJSON geometry shorthand */
interface GeoJSONGeometry {
  type: string;
  coordinates: unknown;
}

/**
 * 정북 일조사선 envelope 응답 구조.
 * Backend: `land/services/envelopes/sunlight.py` (LOCKED SPEC).
 * Renderer: `design/lib/envelopes/sunlight.ts` (LOCKED SPEC).
 *
 * 수정 전 `memory/arr/session14/envelope-locked-spec.md` 확인.
 */
export interface SunlightEnvelope {
  /** 북쪽 수직 직각벽 — 바닥 → H=10m (§86①제1호) */
  walls: {
    positions: [number, number][];   // [[lng, lat], [lng, lat]] — edge 1개당 2점
    min_heights: number[];            // [0.0, 0.0]
    max_heights: number[];            // [10.0, 10.0]
    kind?: string;                    // 'north_vertical'
  }[];
  /** 경사 지붕 polygon (§86①제2호 H=2x, cap 50m) */
  slanted_polygons?: {
    corners: [number, number, number][];  // [[lng, lat, h], ...] — per-vertex 높이
    label?: string;
    kind?: string;                        // 'slope'
  }[];
  /** 정북 ~ PLATEAU_END_M(5m) 띠 평탄부 polygon (§86①제1호 H=10m). Step 13 (2026-05-11). */
  plateau_polygon?: {
    corners: [number, number, number][];  // [[lng, lat, 10], ...]
    label?: string;
    kind?: string;                        // 'plateau'
  } | null;
  /** plateau 띠 폭 (m). 보통 5.0 */
  plateau_end_m?: number;
  /** 2D 단면도용 프로파일 (수직→평탄→경사) */
  profile_polylines?: {
    points: [number, number, number][];
    label?: string;
  }[];
  /** 계단식 envelope 층 (미래 매스 생성 참조용) */
  envelope_layers?: {
    footprint_wgs: [number, number][];
    h_bottom: number;
    h_top: number;
    offset_m: number;
    kind: string;
    label?: string;
  }[];
  /** H 변화 임계값 */
  thresholds?: {
    distance_m: number;
    max_height_m: number;
    kind: string;
  }[];
  slope: number;              // 2.0 (SLOPE)
  base_setback_m: number;     // 1.5 (BASE_SETBACK_M)
  base_height_m: number;      // 10.0 (BASE_HEIGHT_M)
  max_depth_m: number;        // 25.0 (MAX_DEPTH_CAP_M)
  law_basis?: string;

  // ── Phase 2A — datum metadata (시행령 §119, §86) ────────────────
  /** §119/§86 H=0 절대 표고. null = 미계산; 0m는 유효한 표고. */
  datum_elevation_m?: number | null;
  /** "flat"|"slope_le3m"|"slope_gt3m"|"road_flat"|... or null */
  datum_case?: string | null;
  /** "ground_weighted_avg"|"road_centerline"|... or null */
  datum_basis?: string | null;
  /** elevation provider: open_meteo(90m) | copernicus_glo30(30m) | ngii_lidar_1m(14cm) | ngii_local_dem(SHP→DEM) | failed | null */
  elevation_source?: 'open_meteo' | 'copernicus_glo30' | 'ngii_lidar_1m' | 'ngii_5m' | 'ngii_local_dem' | 'failed' | null;
}

/**
 * envelope 미적용 zone (상업/녹지)에서 datum 단독 표시용.
 * backend setback_geometry → setback_lines.datum_result 채움 (Phase 2D-2).
 * design types와 동일 shape 유지.
 */
export interface DatumResultDict {
  elevation_m: number | null;
  case: string | null;
  basis: string | null;
  elevation_source: 'open_meteo' | 'copernicus_glo30' | 'ngii_lidar_1m' | 'ngii_5m' | 'ngii_local_dem' | 'failed' | null;
}

/** 채광 인동간격 검증 결과 */
export interface DaylightDistanceResult {
  distance_m: number;
  required_m: number;
  ratio: number;
  compliant: boolean;
  taller_height_m: number;
  formula: string;
}

/** 규제선 GeoJSON (지�� 시각화용) */
export interface SetbackLines {
  buildable_area?: GeoJSONGeometry | null;
  north_setback?: GeoJSONGeometry | null;
  adjacent_setback?: GeoJSONGeometry | null;
  road_setback?: GeoJSONGeometry | null;
  corner_cutoff?: GeoJSONGeometry | null;
  sunlight_envelope?: SunlightEnvelope | null;
  building_designation_line?: GeoJSONGeometry | null;
  daylight_diagonal_envelope?: SunlightEnvelope | null;
  datum_result?: DatumResultDict | null;
}

/** POST /land/analyze/ 전체 응답 */
export interface LandAnalysisResult {
  pnu: PnuInfo | string | null;
  zone_info: ZoneInfo | null;
  regulations: Regulations | null;
  land_info: LandInfo | null;
  law_articles: LawArticlesResult | null;
  restrictions?: string[];
  overlay_regulations?: OverlayRegulation[];
  setback_lines?: SetbackLines | null;
  errors?: string[];
  warning?: string;
}

// ---------------------------------------------------------------------------
// Agent analysis (SSE streaming)
// ---------------------------------------------------------------------------

/** SSE 이벤트 상태 */
export type AgentAnalysisStatus =
  | 'analyzing'   // Phase 1: 빠른 분석 진행중
  | 'quick_done'  // Phase 1 완료 — 규제 즉시 표시
  | 'agent'       // Phase 2: 에이전트 메시지
  | 'complete'    // 전체 완료
  | 'error';      // 오류

/** Phase 1 진행 이벤트 */
export interface AgentAnalyzingEvent {
  status: 'analyzing';
  phase: string;
  phase_name: string;
  progress: number;
}

/** Phase 1 완료 — 규제 데이터 포함 */
export interface AgentQuickDoneEvent {
  status: 'quick_done';
  regulations: LandAnalysisResult;
  progress: number;
}

/** Phase 2 — 에이전트 메시지 */
export interface AgentMessageEvent {
  status: 'agent';
  agent: string;
  content: string;
  progress: number;
  turn: number;
}

/** 전체 완료 */
export interface AgentCompleteEvent {
  status: 'complete';
  report: string;
  run_summary: { duration: number; total_tokens: number; turn_count: number };
}

/** 오류 */
export interface AgentErrorEvent {
  status: 'error';
  message: string;
  fallback_to_quick?: boolean;
}

/** SSE 이벤트 유니온 */
export type AgentAnalysisEvent =
  | AgentAnalyzingEvent
  | AgentQuickDoneEvent
  | AgentMessageEvent
  | AgentCompleteEvent
  | AgentErrorEvent;

/** 에이전트 메시지 (타임라인 표시용) */
export interface AgentMessage {
  agent: string;
  content: string;
  turn: number;
  timestamp: number;
}

// ---------------------------------------------------------------------------
// /land/resolve/ 응답
// ---------------------------------------------------------------------------

export interface PnuResolveResult {
  success?: boolean;
  pnu?: string;
  valid?: boolean;
  parsed?: PnuInfo;
  coordinates?: { x: number; y: number };
  geocoded_address?: string;
  address?: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// /land/reverse/ 응답
// ---------------------------------------------------------------------------

export interface ReverseGeocodeResult {
  success: boolean;
  pnu: string | null;
  address: string | null;
  geometry: { type: string; coordinates: unknown } | null;
  coordinates: { x: number; y: number };
  error?: string;
}
