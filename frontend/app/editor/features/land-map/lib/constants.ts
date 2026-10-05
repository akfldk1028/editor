/**
 * Land module — 공유 상수
 *
 * Premium dark AI dashboard theme.
 * All colors & tokens centralized here — no hardcoded hex in components.
 */

// ---------------------------------------------------------------------------
// 색상 토큰 (premium dark theme)
// ---------------------------------------------------------------------------

export const COLOR = {
  // Text hierarchy — near-white for numbers, silver cascade for text
  text: '#f0f0f5',           // Primary text / hero numbers
  textSecondary: '#a0a0b0',  // Descriptions
  textMuted: '#6b6b80',      // Labels, captions
  textDim: '#45455a',        // Tertiary, borders

  // Accent — used for glow/borders/badges, NOT for large text
  indigo: '#818cf8',
  amber: '#f59e0b',
  red: '#f87171',
  cyan: '#22d3ee',
  emerald: '#34d399',

  // Surface
  bg: '#0a0a0f',
  panelBg: 'rgba(12,12,18,0.92)',
  glassBorder: 'rgba(255,255,255,0.06)',
  overlay: 'rgba(12,12,18,0.95)',
  overlayBorder: 'rgba(255,255,255,0.08)',

  // Shadow
  panelShadow: '-4px 0 30px rgba(0,0,0,0.5)',

  // Law type badge colors (법률/시행령/시행규칙)
  lawType: {
    '법률': '#3b82f6',
    '시행령': '#8b5cf6',
    '시행규칙': '#f59e0b',
  } as Record<string, string>,
} as const;

// ---------------------------------------------------------------------------
// 공통 스타일 프리셋
// ---------------------------------------------------------------------------

export const STYLE = {
  monoFont: 'ui-monospace, "SF Mono", "Cascadia Mono", monospace',
} as const;

// ---------------------------------------------------------------------------
// 지도 설정
// ---------------------------------------------------------------------------

export const MAP_CONFIG = {
  defaultCenter: [126.978, 37.5665] as [number, number], // Seoul City Hall
  defaultZoom: 17,
  maxZoom: 19,
  minZoom: 5,
  tileUrl: `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/tiles/{z}/{y}/{x}.png`,
  wmsUrl: `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/wms`,
  wmsLayers: 'lp_pa_cbnd_bonbun,lp_pa_cbnd_bubun',
  cadastralMinZoom: 15,
  highlightColor: 'rgba(59, 130, 246, 0.15)',
  highlightStroke: '#3b82f6',
  flyDuration: 800,
} as const;

// ---------------------------------------------------------------------------
// Vworld 3D WebGL 설정
// ---------------------------------------------------------------------------

export const MAP_CONFIG_3D = {
  center: [126.978, 37.5665] as [number, number], // Seoul City Hall
  defaultAltitude: 1200,    // meters — 도시 전경 보기 좋은 높이
  defaultPitch: -45,        // degrees — 비스듬한 3D 시점
  wmsLayers: 'lp_pa_cbnd_bonbun,lp_pa_cbnd_bubun',
  highlightColor: '#3b82f6',
  highlightOpacity: 0.2,
  flyDuration: 1.5,         // seconds
} as const;

// ---------------------------------------------------------------------------
// 규제 메타데이터 (API 응답 key → 표시 이름/단위/색상)
// ---------------------------------------------------------------------------

export interface RegulationMeta {
  name: string;
  unit?: string;
  accent?: string;
  /** API 응답에서 값을 추출하는 key 우선순위 */
  valueKeys: string[];
  /** 설명 텍스트를 추출하는 key 우선순위 */
  descKeys: string[];
}

export const CORE_REGULATIONS: Record<string, RegulationMeta> = {
  bcr:               { name: '건폐율',       unit: '%', accent: COLOR.cyan,   valueKeys: ['limit_pct'],     descKeys: ['rule'] },
  far:               { name: '용적률',       unit: '%', accent: COLOR.emerald, valueKeys: ['limit_pct'],     descKeys: ['rule'] },
  height:            { name: '높이 제한',    unit: 'm',                       valueKeys: ['limit_m'],       descKeys: ['rule'] },
  sunlight_setback:  { name: '일조사선',                                      valueKeys: [],                descKeys: ['rules', 'rule'] },
  corner_cutoff:     { name: '가각전제',                                      valueKeys: [],                descKeys: ['rule'] },
  road_diagonal:     { name: '높이제한 (전면도로)',                              valueKeys: ['multiplier'],    descKeys: ['rule'] },
  building_line:     { name: '건축선 후퇴',  unit: 'm',                       valueKeys: ['setback_m'],     descKeys: ['rule'] },
  adjacent_setback:  { name: '인접대지 이격', unit: 'm',                      valueKeys: ['min_m'],         descKeys: [] },
  parking:           { name: '주차 기준',                                     valueKeys: [],                descKeys: ['rule'] },
  landscaping:       { name: '조경 기준',                                     valueKeys: ['min_pct', 'threshold_m2'], descKeys: [] },
  building_designation: { name: '건축지정선', unit: 'm', accent: '#a855f7',  valueKeys: ['setback_m'],     descKeys: ['rule'] },
};

// ---------------------------------------------------------------------------
// 유틸
// ---------------------------------------------------------------------------

/** Hex color + alpha (0-255 int). Safe fallback if input is not a 7-char hex. */
export function hexA(hex: string, alpha: number): string {
  if (hex.length === 7 && hex[0] === '#') {
    return hex + Math.round(alpha).toString(16).padStart(2, '0');
  }
  // fallback: return as-is (rgba or named colors won't break)
  return hex;
}

/** 19자리 PNU 판별 */
export const PNU_REGEX = /^\d{19}$/;
export const isPnu = (s: string) => PNU_REGEX.test(s.trim());
