import { expect, test } from 'bun:test'
import { GroundResidency } from './ground-residency'

test('recent visits stay resident; eviction protects the current view and revisits refresh recency', () => {
  const cells = new GroundResidency(4)
  expect(cells.visit(['a', 'b'])).toEqual([])
  expect(cells.visit(['c', 'd'])).toEqual([])
  expect(cells.visit(['a'])).toEqual([])
  expect(cells.visit(['e', 'f'])).toEqual(['b', 'c'])
  expect(cells.visit(['a', 'd', 'e', 'f', 'g'])).toEqual([])
  expect(cells.visit(['h'])).toEqual(['a', 'd'])
  cells.clear()
  expect(cells.visit(['a', 'b', 'c', 'd'])).toEqual([])
})

test('size reports resident cells so callers can skip an empty drop', () => {
  const cells = new GroundResidency(2)
  expect(cells.size).toBe(0)
  cells.visit(['a', 'b'])
  cells.visit(['c'])
  expect(cells.size).toBe(2)
  cells.clear()
  expect(cells.size).toBe(0)
})
