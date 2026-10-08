/** Pure derivations for the 이격선 tab: regulation distances, the 정북 envelope's parameters, buildable area. */
import type { RegulationItem, SunlightEnvelope } from '../../../land-map/lib/types'
import type { LawAnalysis } from '../api/analyze'

export interface SetbackRow { key: string; name: string; value: string; note: string | null; basis: string | null }

const meters = (value: number) => `${value.toLocaleString('ko-KR', { maximumFractionDigits: 2 })} m`

function sunlightRule(rule: unknown): string {
  if (typeof rule === 'string') return rule
  const r = (rule ?? {}) as { condition?: string; setback_m?: number; formula?: string }
  const value = r.setback_m != null ? meters(r.setback_m) : r.formula ?? ''
  return r.condition ? `${r.condition}: ${value}` : value
}

/** The distances the regulations state (not drawn): 건축선, 인접대지, 정북 일조, 가각, 높이. */
export function regulationRows(analysis: LawAnalysis): SetbackRow[] {
  const reg = analysis.regulations ?? {}
  const item = (key: string) => (reg[key] ?? null) as RegulationItem | null
  const rows: SetbackRow[] = []
  const line = item('building_line')
  if (line) rows.push({ key: 'building_line', name: '건축선 후퇴', value: line.setback_m != null ? meters(line.setback_m) : '조례 확인', note: line.rule ?? null, basis: line.article ?? null })
  const adjacent = item('adjacent_setback')
  if (adjacent) rows.push({ key: 'adjacent_setback', name: '인접대지 이격', value: adjacent.min_m != null ? `${meters(adjacent.min_m)} 이상` : '—', note: null, basis: adjacent.article ?? null })
  const sunlight = item('sunlight_setback')
  if (sunlight) {
    const rules = (sunlight.rules ?? []).map(sunlightRule).filter(Boolean)
    rows.push({ key: 'sunlight_setback', name: `일조 이격 (${sunlight.direction ?? '정북'})`, value: sunlight.applies === false ? '미적용' : rules.join(' / ') || '적용', note: null, basis: sunlight.article ?? null })
  }
  const corner = item('corner_cutoff')
  if (corner) rows.push({ key: 'corner_cutoff', name: '가각전제', value: corner.required === false ? '미적용' : '적용', note: corner.rule ?? null, basis: corner.article ?? null })
  const height = item('height')
  if (height) rows.push({ key: 'height', name: '높이 제한', value: height.limit_m != null ? meters(height.limit_m) : '가로구역별', note: height.rule ?? null, basis: height.article ?? null })
  return rows
}

const THRESHOLD_LABEL: Record<string, string> = { vertical: '수직부', plateau: '평탄부', slope_top: '경사 상단', cap: '상한' }

/** The §86 envelope's numbers (the 3D shape itself stays on the map). */
export function envelopeRows(envelope: SunlightEnvelope | null | undefined): SetbackRow[] {
  if (!envelope) return []
  const rows: SetbackRow[] = [
    { key: 'base_setback', name: '기준 이격 (H ≤ 기준 높이)', value: meters(envelope.base_setback_m), note: null, basis: null },
    { key: 'base_height', name: '기준 높이', value: meters(envelope.base_height_m), note: envelope.plateau_end_m != null ? `평탄부 ${meters(envelope.plateau_end_m)}까지` : null, basis: null },
    { key: 'slope', name: '경사 (높이 = 이격 × 배수)', value: `× ${envelope.slope}`, note: null, basis: null },
    { key: 'max_depth', name: '최대 적용 깊이', value: meters(envelope.max_depth_m), note: null, basis: null },
  ]
  for (const threshold of envelope.thresholds ?? []) {
    rows.push({ key: `threshold-${threshold.kind}`, name: `구간 · ${THRESHOLD_LABEL[threshold.kind] ?? threshold.kind}`, value: `이격 ${meters(threshold.distance_m)} → 최고 ${meters(threshold.max_height_m)}`, note: null, basis: null })
  }
  if (envelope.datum_elevation_m != null) {
    rows.push({ key: 'datum', name: '기준 표고 (H = 0)', value: `${envelope.datum_elevation_m.toLocaleString('ko-KR', { maximumFractionDigits: 2 })} m`, note: [envelope.datum_case, envelope.datum_basis, envelope.elevation_source].filter(Boolean).join(' · ') || null, basis: null })
  }
  if (envelope.law_basis) rows[0] = { ...rows[0]!, basis: envelope.law_basis }
  return rows
}

type Ring = [number, number][]

function rings(geometry: unknown): Ring[] {
  if (!geometry || typeof geometry !== 'object') return []
  const g = geometry as { type?: string; coordinates?: unknown; geometry?: unknown; features?: unknown[] }
  switch (g.type) {
    case 'Polygon': return Array.isArray(g.coordinates) && Array.isArray(g.coordinates[0]) ? [g.coordinates[0] as Ring] : []
    case 'MultiPolygon': return Array.isArray(g.coordinates) ? (g.coordinates as Ring[][]).map((polygon) => polygon[0]!).filter(Boolean) : []
    case 'Feature': return rings(g.geometry)
    case 'FeatureCollection': return (g.features ?? []).flatMap(rings)
    default: return []
  }
}

const M_PER_DEG = 111_320

/** Planar shoelace on a local equirectangular projection — within 1% at parcel scale. Null without a ring. */
export function geometryAreaM2(geometry: unknown): number | null {
  const all = rings(geometry).filter((ring) => ring.length >= 3)
  if (!all.length) return null
  let total = 0
  for (const ring of all) {
    const lat0 = (ring.reduce((sum, [, lat]) => sum + lat, 0) / ring.length) * (Math.PI / 180)
    const kx = M_PER_DEG * Math.cos(lat0)
    let sum = 0
    for (let i = 0; i < ring.length; i++) {
      const [x1, y1] = ring[i]!
      const [x2, y2] = ring[(i + 1) % ring.length]!
      sum += x1 * kx * (y2 * M_PER_DEG) - x2 * kx * (y1 * M_PER_DEG)
    }
    total += Math.abs(sum) / 2
  }
  return total
}

export interface BuildableSummary { areaM2: number | null; ratioPct: number | null; drawn: string[]; missing: string[] }

const LINE_NAMES: Record<string, string> = {
  north_setback: '정북 이격선', adjacent_setback: '인접대지 이격선', road_setback: '도로 후퇴선',
  corner_cutoff: '가각전제', building_designation_line: '건축지정선',
}

/** 건축가능영역 area against the land area, and which lines the engine drew or left out. */
export function buildableSummary(analysis: LawAnalysis): BuildableSummary {
  const lines = analysis.setback_lines ?? {}
  const areaM2 = geometryAreaM2(lines.buildable_area)
  const land = analysis.land_info?.land_area_m2
  const ratioPct = areaM2 !== null && typeof land === 'number' && land > 0 ? (areaM2 / land) * 100 : null
  const drawn: string[] = []
  const missing: string[] = []
  for (const [key, name] of Object.entries(LINE_NAMES)) ((lines as Record<string, unknown>)[key] ? drawn : missing).push(name)
  return { areaM2, ratioPct, drawn, missing }
}
