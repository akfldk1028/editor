import { expect, test } from 'bun:test'
import { FootprintIndex } from './footprint-index'
import { overlaps, type Footprint } from './building-geometry'

const square = (x: number, y: number, size: number): Footprint => ({ key: `${x}/${y}`, pnu: '', h: 10, s: 'm',
  ring: [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]] })

test('spatial lookup agrees with polygon matching across cells and oversized footprints', () => {
  const features = Array.from({ length: 200 }, (_, i) => square(127 + i % 20 * .001, 37 + Math.floor(i / 20) * .001, .0006))
  features.push(square(128, 38, .1))
  const index = new FootprintIndex(features)
  for (let i = 0; i < 300; i++) {
    const f = square(127 + i % 25 * .0009, 37 + Math.floor(i / 25) * .0009, .0001)
    expect(index.overlaps(f)).toBe(features.some(t => overlaps(f, t)))
  }
  expect(index.overlaps(square(128.05, 38.05, .0001))).toBe(true)
  expect(index.overlaps(square(126.9, 36.9, 1))).toBe(true)
  expect(index.overlaps(square(130, 40, .001))).toBe(false)
})

test('a courtyard annex is not suppressed as an overlapping enclosing building', () => {
  for (const scale of [.0001, .1]) {
    const enclosing = { ...square(127, 37, scale * 10), holes: [square(127 + scale, 37 + scale, scale * 8).ring] }
    const annex = square(127 + scale * 3, 37 + scale * 3, scale)
    expect(overlaps(enclosing, annex)).toBe(false)
    expect(overlaps(annex, enclosing)).toBe(false)
    expect(new FootprintIndex([enclosing]).overlaps(annex)).toBe(false)
    expect(new FootprintIndex([annex]).overlaps(enclosing)).toBe(false)
    const crossing = square(127 + scale * .5, 37 + scale * 3, scale)
    expect(new FootprintIndex([enclosing]).overlaps(crossing)).toBe(true)
    expect(new FootprintIndex([enclosing]).overlaps({ ...enclosing })).toBe(true)
  }
})
