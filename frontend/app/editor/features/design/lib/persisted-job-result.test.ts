import { expect, test } from 'bun:test'
import { persistedJobResult } from './persisted-job-result'

test('persisted recovery retains floor plates and MAAS geometry for rendering and operations', () => {
  const feature = { type: 'Feature', geometry: { type: 'Polygon', coordinates: [] },
    properties: { floor_plates: [{ top_height: 3 }], maas_model: { surfaces: [1] }, algorithm: 'maas_legal_envelope' } }
  const result = persistedJobResult({ job: { status: 'complete', generation_count: 2 }, total_designs: 1,
    designs: [{ design_id: 0, is_pareto_optimal: true, mass_geojson: feature }] })
  expect(result?.status).toBe('complete')
  expect(result && 'paretoGeojson' in result && result.paretoGeojson[0]).toEqual(feature)
  expect(result && 'best' in result && result.best?.id).toBe(0)
})

test('polling finishes for failed, cancelled and empty completed jobs instead of waiting forever', () => {
  expect(persistedJobResult({ job: { status: 'failed', error: 'worker interrupted' } })).toEqual({ status: 'error', error: 'worker interrupted' })
  expect(persistedJobResult({ job: { status: 'cancelled' } })?.status).toBe('cancelled')
  expect(persistedJobResult({ job: { status: 'complete' }, designs: [] })?.status).toBe('complete')
  expect(persistedJobResult({ job: { status: 'running' } })).toBeNull()
})

test('polling recovery restores objective labels and generation budget without SSE started', () => {
  const objectives = [{ name: 'daylight_score', goal: 'Minimize' }]
  const result = persistedJobResult({ job: { status: 'complete', max_generations: 3, objectives }, designs: [] })
  expect(result).toMatchObject({ objectives, maxGenerations: 3 })
  const legacy = persistedJobResult({ job: { status: 'complete' }, designs: [] })
  expect(legacy).toMatchObject({ objectives: [], maxGenerations: 0 })
})

test('legacy duplicate IDs retain their stored UIDs when geometry lacks identity metadata', () => {
  const feature = { type:'Feature', geometry:{type:'Polygon',coordinates:[]}, properties:{} }
  const result = persistedJobResult({job:{status:'complete'},designs:['additive:7','subtractive:7'].map(uid => ({
    design_id:7,is_pareto_optimal:true,mass_geojson:feature,outputs:{result_identity:{uid}},
  }))})
  expect(result && 'paretoFront' in result && result.paretoFront.map(item=>({id:item.id,uid:item.uid}))).toEqual([
    {id:7,uid:'additive:7'},{id:7,uid:'subtractive:7'},
  ])
  expect(feature.properties).toEqual({})
})
