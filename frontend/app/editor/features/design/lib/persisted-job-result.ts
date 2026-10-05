import type { DesignData, GeoJSONFeature } from './types'

export function persistedJobResult(payload: any) {
  const status = payload?.job?.status
  if (status === 'failed' || status === 'cancelled') {
    return { status: status === 'failed' ? 'error' as const : 'cancelled' as const,
      error: status === 'failed' ? payload.job.error || 'Optimization failed' : null }
  }
  if (status !== 'complete') return null
  const designs = Array.isArray(payload.designs) ? payload.designs : []
  const persisted = designs.filter((design: any) => design?.is_pareto_optimal && design?.mass_geojson)
  const paretoGeojson: GeoJSONFeature[] = persisted.map((design: any) => design.mass_geojson)
  const paretoFront: DesignData[] = persisted.map((design: any, index: number) => {
    const properties = design.mass_geojson.properties || {}
    return { id: design.design_id ?? properties.design_id ?? index + 1,
      uid: design.outputs?.result_identity?.uid || properties.design_uid, generation: design.generation ?? 0, parents: [null, null],
      feasible: design.is_feasible ?? true, inputs: Array.isArray(design.inputs) ? design.inputs : [],
      objectives: Array.isArray(design.outputs?.objectives) ? design.outputs.objectives :
        [properties.floor_area ?? properties.floorArea ?? 0, properties.open_pct ?? properties.openPct ?? 0],
      penalty: design.outputs?.penalty ?? 0, rank: design.ranking ?? 1, elite: 0, algorithm: properties.algorithm }
  })
  return { status: 'complete' as const, error: null, paretoFront, paretoGeojson,
    best: paretoFront[0] ?? null, bestGeojson: paretoGeojson[0] ?? null,
    totalDesigns: payload.total_designs ?? paretoFront.length, progress: 100,
    generation: payload.job.generation_count ?? 0,
    maxGenerations: payload.job.max_generations ?? 0,
    objectives: Array.isArray(payload.job.objectives) ? payload.job.objectives : [] }
}
