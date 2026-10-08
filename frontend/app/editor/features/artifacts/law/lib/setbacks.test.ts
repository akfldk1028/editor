import { expect, test } from 'bun:test'

import { buildableSummary, envelopeRows, geometryAreaM2, regulationRows } from './setbacks'
import { fixture } from './summary.fixture'

test('regulation rows state the distances the regulations give, in order', () => {
  const rows = regulationRows(fixture)
  expect(rows.map((row) => row.key)).toEqual(['building_line', 'adjacent_setback', 'sunlight_setback', 'corner_cutoff', 'height'])
  expect(rows[0]!.value).toBe('조례 확인')
  expect(rows[1]!.value).toBe('0.5 m 이상')
  expect(rows[2]!.value).toBe('H <= 10m: 1.5 m / H > 10m: H * 0.5')
  expect(rows[3]!.value).toBe('적용')
  expect(rows[4]!.value).toBe('가로구역별')
  expect(regulationRows({ ...fixture, regulations: null })).toEqual([])
})

test('envelope rows carry the §86 parameters, thresholds and the datum', () => {
  const rows = envelopeRows(fixture.setback_lines!.sunlight_envelope)
  expect(rows[0]).toMatchObject({ value: '1.5 m', basis: '건축법 §61①, 시행령 §86①' })
  expect(rows[1]).toMatchObject({ value: '10 m', note: '평탄부 5 m까지' })
  expect(rows[2]!.value).toBe('× 2')
  expect(rows.find((row) => row.key === 'threshold-cap')).toMatchObject({ name: '구간 · 상한', value: '이격 25 m → 최고 50 m' })
  expect(rows.find((row) => row.key === 'datum')!.value).toBe('0 m')
  expect(envelopeRows(null)).toEqual([])
})

test('geometry area is a planar shoelace in metres (square ~110 m × 88 m at 37.73°N)', () => {
  const area = geometryAreaM2(fixture.setback_lines!.buildable_area)!
  expect(area).toBeGreaterThan(9_600)
  expect(area).toBeLessThan(9_900)
  const asCollection = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: fixture.setback_lines!.buildable_area }] }
  expect(geometryAreaM2(asCollection)).toBeCloseTo(area, 6)
  expect(geometryAreaM2({ type: 'Point', coordinates: [127, 37] })).toBeNull()
  expect(geometryAreaM2(null)).toBeNull()
})

test('the buildable summary ratios against the land area and lists drawn and missing lines', () => {
  const summary = buildableSummary(fixture)
  expect(summary.ratioPct).toBeGreaterThan(380)
  expect(summary.drawn).toEqual(['정북 이격선', '인접대지 이격선'])
  expect(summary.missing).toEqual(['도로 후퇴선', '가각전제', '건축지정선'])
  expect(buildableSummary({ ...fixture, setback_lines: null })).toMatchObject({ areaM2: null, ratioPct: null, drawn: [] })
})
