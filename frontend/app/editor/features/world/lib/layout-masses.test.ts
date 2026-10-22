import { describe, expect, test } from 'bun:test'
import { BASEMENT_STOREY_M, drawLayout, levelDepth, rampHeights, showUnderground, type LayoutFeature, type LayoutView } from './layout-masses'

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
    expect(showUnderground(Cesium, globe, view([feature('basement_boundary', -1, square(LON, LAT, 0.0003))]))).toBe(true)
    expect(globe.translucency.enabled).toBe(true)
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
