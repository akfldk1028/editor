import type { AutoConstraintsResult, Constraint, SetbackGeometriesMap } from './types'

type LandAnalysis = {
  zone_info?: { zones?: string[] } | null
  regulations?: Record<string, { limit_pct?: number | null; limit_m?: number | null; min_m?: number | null; setback_m?: number | null; status?: string }> | null
  setback_lines?: Record<string, unknown> | null
  law_articles?: AutoConstraintsResult['law_articles'] | null
  warning?: string
  errors?: string[]
}

export function toDesignConstraints(analysis: LandAnalysis, buildingType?: string): AutoConstraintsResult {
  if (!analysis.regulations) throw new Error(analysis.warning || '대지의 용도지역을 확인하지 못했습니다.')
  const reg = analysis.regulations
  const bcr = reg.bcr?.limit_pct ?? null
  const far = reg.far?.limit_pct ?? null
  const height = reg.height?.limit_m ?? null
  const setback = reg.adjacent_setback?.min_m ?? null
  const rules = [
    ['bcr', bcr, '%', '건폐율', 'Less than'],
    ['far', far, '%', '용적률', 'Less than'],
    ['height', height, 'm', '높이', 'Less than'],
    ['setback', setback, 'm', '인접대지 이격', 'Greater than'],
  ] as const
  const constraints: Constraint[] = rules.flatMap(([name, val, unit, label, Requirement]) =>
    typeof val === 'number' && Number.isFinite(val)
      ? [{ name, type: 'Constraint' as const, Requirement, val, unit, label }]
      : [])
  const geometries: Record<string, unknown> = {}
  for (const [name, value] of Object.entries(analysis.setback_lines || {})) {
    if (!value) continue
    if (name.endsWith('_envelope') || name === 'datum_result' || name === 'road_frontages' || name === 'neighbor_parcels') {
      geometries[name] = value
    } else if (typeof value === 'object' && 'type' in value) {
      geometries[name] = { geometry: value, label: name, distance_m: name === 'adjacent_setback' ? setback : null }
    }
  }
  return {
    zones: analysis.zone_info?.zones || [], constraints,
    regulations: { bcr_pct: bcr, far_pct: far, height_limit_m: height, adjacent_setback_m: setback },
    setback_geometries: geometries as SetbackGeometriesMap,
    law_articles: analysis.law_articles || undefined, building_type: buildingType,
  }
}
