import { test, expect } from 'bun:test'
import { refreshGroundRoads } from './refresh-ground-roads'

test('refresh replaces only roads, preserves ground evidence and refuses unproven replacements', () => {
  const parcel = { properties: { layer: 'ground' } }, road = { properties: { layer: 'carriageway', width_m: 8 } }
  const full = { status: 'ok', record: { ground: { retrieved: 'original' } },
    features: { type: 'FeatureCollection', features: [parcel, { properties: { layer: 'carriageway', width_m: 4 } }] } }
  const roads = { status: 'ok', record: { roads: { revision: 'current' } }, features: { type: 'FeatureCollection', features: [road] } }
  const result = refreshGroundRoads(full, roads)
  expect(result.features.features).toEqual([parcel, road])
  expect(result.record.ground).toBe(full.record.ground)
  expect(() => refreshGroundRoads(full, { status: 'needs_evidence' })).toThrow()
  expect(() => refreshGroundRoads(full, { ...roads, record: {} })).toThrow()
})
