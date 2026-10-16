import { describe, expect, test } from 'bun:test'
import { overlaps, tilesIn, type Footprint } from './building-geometry'

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

test('visible tiles are bounded and nearest first', () => {
  const result = tilesIn([126.9, 37.4, 127.2, 37.8], { lon: 127, lat: 37.5 })
  expect(result).toHaveLength(40)
  expect(new Set(result.map(t => t.key)).size).toBe(40)
})
