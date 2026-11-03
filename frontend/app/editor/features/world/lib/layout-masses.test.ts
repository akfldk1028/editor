import { describe, expect, test } from 'bun:test'
import { BASEMENT_STOREY_M, clearLayout, drawLayout, excavate, levelDepth, rampHeights, showUnderground, type LayoutFeature, type LayoutView } from './layout-masses'

/* eslint-disable @typescript-eslint/no-explicit-any */
const colour = { withAlpha: () => colour }
const Cesium: any = {
  Color: { fromCssColorString: () => colour },
  Cartesian3: {
    fromDegreesArray: (a: number[]) => ({ flat: a }),
    fromDegreesArrayHeights: (a: number[]) => ({ heights: a.filter((_, k) => k % 3 === 2) }),
  },
  HeightReference: { RELATIVE_TO_GROUND: 'rel' },
  Rectangle: { fromDegrees: (...b: number[]) => b },
  PolylineDashMaterialProperty: class {},
}

function entities() {
  const added: any[] = []
  return { added, values: added, add: (e: any) => added.push(e), remove: () => {}, suspendEvents: () => {}, resumeEvents: () => {} }
}

const square = (x: number, y: number, d = 0.0001) => ({
  type: 'Polygon',
  coordinates: [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]],
})
const feature = (layer: string, level: number, geometry: any, extra: object = {}): LayoutFeature => ({
  type: 'Feature', geometry, properties: { layer, level, area_m2: null, ...extra },
})
const PROFILE = [{ distance_m: 0, z_m: 0 }, { distance_m: 6, z_m: 0 }, { distance_m: 30, z_m: -3.3 }]
const LON = 127.1
const LAT = 37.73
// a 30 m centreline running east from (LON, LAT)
const EAST_30M = 30 / (111_320 * Math.cos((LAT * Math.PI) / 180))

function view(features: LayoutFeature[]): LayoutView {
  return { features, storeys: 4, storey_height_m: 3.5, height_m: 14, height_basis: null, footprint_m2: 800, coverage_pct: 32 }
}

test('planned building masses remain opaque for unknown floors and glazed facade intents', () => {
  const color = (css: string, alpha = 1): any => ({ css, alpha, withAlpha: (next: number) => color(css, next) })
  const C = { ...Cesium, Color: { fromCssColorString: color } }
  for (const storeys of [null, 5]) for (const intent of [null, { material_attitude: '커튼월' }]) {
    const e = entities()
    drawLayout(e, C, { ...view([feature('building_footprint', 0, square(LON, LAT))]), storeys }, intent, 60)
    expect(e.added[0].polygon.material.alpha).toBe(1)
  }
  const e = entities()
  drawLayout(e, C, { ...view([feature('building_footprint', 0, square(LON, LAT))]),
    mass: { label: 'test', volumes: [{ ring: square(LON, LAT).coordinates[0]!, base_m: 0, top_m: 17.5 }] } },
    { material_attitude: 'glass' }, 60)
  expect(e.added[0].polygon.material.alpha).toBe(1)
})

test('identical polled layouts retain live entities while design, ground and clear changes redraw', () => {
  const e = entities()
  let removals = 0
  e.remove = (entity?: any) => { removals++; const i = e.values.indexOf(entity); if (i >= 0) e.values.splice(i, 1) }
  const layout = view([feature('building_footprint', 0, square(LON, LAT))])
  drawLayout(e, Cesium, layout, null, 60)
  const original = e.values[0]
  expect(drawLayout(e, Cesium, structuredClone(layout), null, 60)).toBe(1)
  expect(e.values[0]).toBe(original)
  expect(e.values).toHaveLength(1)
  expect(removals).toBe(0)
  drawLayout(e, Cesium, { ...layout, height_m: 21 }, null, 60)
  expect(e.values[0]).not.toBe(original)
  expect(e.values[0].polygon.extrudedHeight).toBe(81)
  const updated = e.values[0]
  drawLayout(e, Cesium, { ...layout, height_m: 21 }, null, 'terrain')
  expect(e.values[0]).not.toBe(updated)
  expect(e.values[0].polygon.extrudedHeightReference).toBe('rel')
  clearLayout(e)
  expect(e.values).toHaveLength(0)
  drawLayout(e, Cesium, { ...layout, height_m: 21 }, null, 'terrain')
  expect(e.values).toHaveLength(1)
})

describe('basement in the 3D layout', () => {
  test('a basement level is drawn one storey down; the ground stays at 0', () => {
    expect(levelDepth(0)).toBe(0)
    expect(levelDepth(-1)).toBe(-BASEMENT_STOREY_M)
    expect(levelDepth(-2)).toBeCloseTo(-6.6)
  })

  test('basement stalls and plate are drawn below the ground, ground stalls on it', () => {
    const e = entities()
    drawLayout(e, Cesium, view([
      feature('parking_stall', 0, square(LON, LAT)),
      feature('parking_stall', -1, square(LON, LAT)),
      feature('basement_boundary', -1, square(LON, LAT, 0.0003)),
    ]), null, 50)
    const heights = Object.fromEntries(e.added.map((x) => [x.name, x.polygon.height]))
    expect(heights['주차 구획']).toBeCloseTo(50.25)
    expect(heights['지하 1층 주차 구획']).toBeCloseTo(50 - 3.3 + 0.25)
    expect(heights['지하 1층 바닥']).toBeCloseTo(50 - 3.3)
  })

  test('on terrain the basement is placed relative to the ground at its depth', () => {
    const e = entities()
    drawLayout(e, Cesium, view([feature('parking_aisle', -1, square(LON, LAT))]), null, 'terrain')
    expect(e.added[0].polygon.height).toBeCloseTo(-3.3 + 0.25)
    expect(e.added[0].polygon.heightReference).toBe('rel')
  })

  test('the ramp follows its own profile along the centreline', () => {
    const line = [LON, LAT, LON + EAST_30M, LAT]
    const ring = [LON, LAT, LON + EAST_30M / 2, LAT, LON + EAST_30M, LAT]
    const z = rampHeights(ring, line, PROFILE)
    expect(z[0]).toBeCloseTo(0)
    expect(z[1]).toBeCloseTo(-3.3 * (9 / 24), 1)
    expect(z[2]).toBeCloseTo(-3.3, 1)

    const e = entities()
    drawLayout(e, Cesium, view([
      feature('ramp_centerline', -1, { type: 'LineString', coordinates: [[LON, LAT], [LON + EAST_30M, LAT]] }),
      feature('ramp', -1, { type: 'Polygon', coordinates: [[[LON, LAT], [LON + EAST_30M, LAT], [LON + EAST_30M, LAT + 0.00005], [LON, LAT + 0.00005], [LON, LAT]]] }, { profile: PROFILE }),
    ]), null, 10)
    const ramp = e.added.find((x) => x.name === '램프')
    expect(ramp.polygon.perPositionHeight).toBe(true)
    expect(Math.max(...ramp.polygon.hierarchy.heights)).toBeCloseTo(10)
    expect(Math.min(...ramp.polygon.hierarchy.heights)).toBeCloseTo(10 - 3.3, 1)
  })

  test('the ground turns see-through over the basement only, and back when there is none', () => {
    const globe: any = { translucency: { enabled: false } }
    expect(showUnderground(Cesium, globe, view([feature('basement_boundary', -1, square(LON, LAT, 0.0003))]))).toBe(false)
    expect(globe.translucency.enabled).toBe(false)
    expect(showUnderground(Cesium, globe, view([feature('basement_boundary', -1, square(LON, LAT, 0.0003))]), true)).toBe(true)
    expect(globe.translucency.enabled).toBe(true)
    // Translucent back faces would turn the whole globe in view see-through.
    expect(globe.translucency.backFaceAlpha).toBe(1)
    const [w, s, east, n] = globe.translucency.rectangle
    expect(w).toBeLessThan(LON)
    expect(east).toBeGreaterThan(LON + 0.0003)
    expect(s).toBeLessThan(LAT)
    expect(n).toBeGreaterThan(LAT + 0.0003)
    expect(showUnderground(Cesium, globe, view([feature('parking_stall', 0, square(LON, LAT))]))).toBe(false)
    expect(globe.translucency.enabled).toBe(false)
    expect(showUnderground(Cesium, globe, null)).toBe(false)
  })
})

test('a chosen Mass form with a delivered model is drawn as that model, not as storey boxes', () => {
  const C = {
    ...Cesium,
    Cartesian3: { ...Cesium.Cartesian3, fromDegrees: (lng: number, lat: number, h: number) => ({ lng, lat, h }) },
    Transforms: { headingPitchRollQuaternion: (_p: any, hpr: any) => ({ heading: hpr.heading }) },
    HeadingPitchRoll: class { constructor(public heading: number) {} },
    Math: { toRadians: (d: number) => (d * Math.PI) / 180 },
    CustomShader: class { constructor(public options: any) {} },
    LightingModel: { UNLIT: 'unlit' },
  }
  const e = entities()
  drawLayout(e, C, { ...view([feature('building_footprint', 0, square(LON, LAT))]),
    mass: { label: 'm', volumes: [{ ring: square(LON, LAT).coordinates[0]!, base_m: 0, top_m: 3 }],
      model: { href: 'design/maas/delivered-mass-export/h/files/selected.glb', origin: [LON, LAT], heading_deg: -1.15 } } },
    null, 'terrain')
  const masses = e.added.filter((x) => String(x.id).includes('building-mass'))
  expect(masses).toHaveLength(1)
  expect(masses[0].model.uri).toBe('/api/v1/design/maas/delivered-mass-export/h/files/selected.glb')
  expect(masses[0].model.heightReference).toBe('rel')
  expect(masses[0].model.customShader.options.fragmentShaderText).toContain('dFdx')
  expect(masses[0].orientation.heading).toBeCloseTo(((-1.15 + 90) * Math.PI) / 180)
})

test('the ground is cut open along the basement outline only, and closed again without one', () => {
  const C = { ...Cesium,
    ClippingPolygonCollection: class { constructor(public options: any) {} },
    ClippingPolygon: class { constructor(public options: any) {} } }
  const globe: any = {}
  expect(excavate(C, globe, view([feature('basement_boundary', -1, square(LON, LAT, 0.0003))]))).toBe(true)
  expect(globe.clippingPolygons.options.polygons).toHaveLength(1)
  expect(excavate(C, globe, view([feature('parking_stall', 0, square(LON, LAT))]))).toBe(false)
  expect(globe.clippingPolygons).toBeUndefined()
})
