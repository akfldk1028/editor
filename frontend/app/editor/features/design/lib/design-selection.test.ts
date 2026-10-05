import { expect, test } from 'bun:test'
import { featureFitsSite, matchesDesignFeature, normalizeSitePolygon, pickDiverseParetoDesigns } from './design-selection'
import type { DesignData, GeoJSONFeature } from './types'

const ring = (x: number, y: number, size: number) => [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]
const feature = (coordinates: number[][], id = 1, algorithm = 'alpha') => ({
  type: 'Feature', geometry: { type: 'Polygon', coordinates: [coordinates] },
  properties: { design_id: id, algorithm },
}) as GeoJSONFeature
const design = (id: number, algorithm: string) => ({
  id, algorithm, objectives: [id, id], penalty: 0,
}) as DesignData

test('normalizes a multipolygon to its largest parcel without changing a polygon', () => {
  const small = [ring(20, 20, 1)]
  const large = [ring(0, 0, 10)]
  expect(normalizeSitePolygon({ type: 'MultiPolygon', coordinates: [small, large] })).toEqual({ type: 'Polygon', coordinates: large })
  const polygon = { type: 'Polygon', coordinates: large }
  expect(normalizeSitePolygon(polygon)).toBe(polygon)
})

test('rejects a mass outside the site while accepting an interior or boundary-aligned mass', () => {
  const site = { type: 'Polygon', coordinates: [ring(0, 0, 10)] }
  expect(featureFitsSite(feature(ring(1, 1, 2)), site)).toBe(true)
  expect(featureFitsSite(feature(ring(0, 0, 10)), site)).toBe(true)
  expect(featureFitsSite(feature(ring(8, 8, 5)), site)).toBe(false)
  expect(featureFitsSite(feature(ring(20, 20, 1)), site)).toBe(false)
})

test('keeps same-numbered candidates from different algorithms distinct', () => {
  expect(matchesDesignFeature(feature(ring(0, 0, 1), 1, 'alpha'), design(1, 'beta'))).toBe(false)
  const candidates = [design(1, 'alpha'), design(1, 'beta'), design(2, 'alpha')]
  const selected = pickDiverseParetoDesigns(candidates, [], null, 2)
  expect(selected).toHaveLength(2)
  expect(new Set(selected.map(item => item.algorithm)).size).toBe(2)
  expect(candidates.map(item => item.id)).toEqual([1, 1, 2])
})
