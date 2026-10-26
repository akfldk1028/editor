import { describe, expect, test } from 'bun:test'
import { decodeBuildings, overlaps, selectBuildingDetail, tileXY, tilesIn, type Footprint } from './building-geometry'

const square = (x: number, y: number, size = 1): Footprint => ({
  key: `${x}/${y}`, pnu: 'same-parcel', h: 10, s: 'm',
  ring: [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]],
})

describe('building identity', () => {
  test('different buildings on one parcel survive', () => {
    expect(overlaps(square(0, 0), square(2, 0))).toBe(false)
  })
  test('overlapping footprints from different sources are duplicates', () => {
    expect(overlaps(square(0, 0), { ...square(0.5, 0.5), pnu: 'other' })).toBe(true)
    expect(overlaps(square(0, 0, 4), square(1, 1))).toBe(true)
  })
  test('crossing edges with no interior vertex are detected', () => {
    const a = { ...square(0, 0), ring: [[0, 1], [3, 1], [3, 2], [0, 2], [0, 1]] }
    const b = { ...square(0, 0), ring: [[1, 0], [2, 0], [2, 3], [1, 3], [1, 0]] }
    expect(overlaps(a, b)).toBe(true)
  })
})

test('a wide view uses coarse tiles covering both edges instead of cutting off the neighbourhood', () => {
  const box: [number, number, number, number] = [126.9, 37.4, 127.2, 37.8]
  const result = tilesIn(box, { lon: 127, lat: 37.5 })
  const z = result[0]!.z
  expect(z).toBeLessThan(16)
  expect(result.length).toBeLessThanOrEqual(256)
  for (const [lon, lat] of [[box[0], box[1]], [box[2], box[3]]]) {
    const [x, y] = tileXY(lon!, lat!, z)
    expect(result.some(t => t.x === x && t.y === y)).toBe(true)
  }
  const [x, y] = tileXY(127, 37.5, z)
  expect(result[0]).toMatchObject({ x, y })
})

test('a close view preserves the detailed buildings', () => {
  expect(tilesIn([127, 37.5, 127.001, 37.501], { lon: 127, lat: 37.5 }).every(t => t.z === 16)).toBe(true)
})

test('decoding coarse tiles uses that tiles zoom for geographic coordinates', async () => {
  class Pbf { constructor(_: unknown) {} }
  class VectorTile {
    layers = { buildings: { length: 1, feature: () => ({ type: 3, extent: 4096, properties: { h: 10 },
      loadGeometry: () => [[{ x: 0, y: 0 }, { x: 4096, y: 0 }, { x: 4096, y: 4096 }, { x: 0, y: 0 }]] }) } }
  }
  const [f] = await decodeBuildings(new Uint8Array(), { z: 13, x: 4096, y: 4096, key: '13/4096/4096' }, Pbf, VectorTile)
  expect(f!.ring[0]).toEqual([0, 0])
  expect(f!.ring[1]![0]).toBeCloseTo(360 / 8192, 8)
})

test('coarse detail bounds geometry while preserving large landmarks and full close detail', () => {
  const features = Array.from({ length: 1000 }, (_, i) => square(i, 0, i === 999 ? 20 : 1))
  const far = selectBuildingDetail(features, 13)
  expect(far).toHaveLength(160)
  expect(far).toContain(features[999]!)
  expect(selectBuildingDetail(features, 16)).toBe(features)
})

test('dense tile decoding yields to input and stops on disposal', async () => {
  let parsed = 0
  class Pbf { constructor(_: unknown) {} }
  class VectorTile {
    layers = { buildings: { length: 100, feature: () => {
      parsed++
      const until = performance.now() + 1
      while (performance.now() < until) { /* costly vector decoding */ }
      return { type: 3, extent: 4096, properties: { h: 10 }, loadGeometry: () => [] }
    } } }
  }
  const controller = new AbortController()
  const result = decodeBuildings(new Uint8Array(), { z: 16, x: 0, y: 0, key: '16/0/0' }, Pbf, VectorTile, controller.signal)
  const outcome = result.then(() => null, error => error)
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(parsed).toBeGreaterThan(0)
  expect(parsed).toBeLessThan(100)
  controller.abort()
  expect(await outcome).not.toBeNull()
})
