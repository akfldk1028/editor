import { expect, test } from 'bun:test'
import { enrichGround, canResumeGround, selectGroundLeaves } from './building-ground-publication'
import type { Footprint } from '../features/world/lib/building-geometry'

const footprint = (z?: number): Footprint => ({ key: 'b', pnu: '', ring: [[127, 37]], h: 12, s: 'm', z })

test('refresh fills only derived ground in bounded batches and preserves measured building heights', async () => {
  const original = footprint(93), derived = Array.from({ length: 2050 }, () => footprint())
  const batches: number[] = []
  const result = await enrichGround([original, ...derived], 'new', async points => {
    batches.push(points.length)
    return { heights: points.map(() => 101), source: { fileSignature: 'new' } }
  })
  expect(batches).toEqual([1024, 1024, 2])
  expect(original.z).toBe(93)
  expect(original.h).toBe(12)
  expect(derived.every(f => f.z === 101 && f.h === 12 && f.s === 'm')).toBe(true)
  expect(result).toEqual({ fileSignature: 'new' })
})

test('a changing DEM never partially applies a mixed-revision batch', async () => {
  const features = Array.from({ length: 1025 }, () => footprint())
  let calls = 0
  await expect(enrichGround(features, 'first', async points => ({ heights: points.map(() => 22),
    source: { fileSignature: ++calls === 1 ? 'first' : 'second' } }))).rejects.toThrow('DEM source changed')
  expect(features.every(f => f.z === undefined)).toBe(true)
})

test('refresh resume requires the same derived-ground revision but preserves archive-only regions', () => {
  expect(canResumeGround({ groundPolicy: 'local-dem', groundRevision: 'old' }, 'new')).toBe(false)
  expect(canResumeGround({ groundPolicy: 'local-dem', groundRevision: 'new' }, 'new')).toBe(true)
  expect(canResumeGround({ groundPolicy: 'archive' }, 'new')).toBe(true)
  expect(canResumeGround({}, 'new')).toBe(false)
})

test('NoData does not fabricate a datum or alter source height', async () => {
  const features = [footprint(), footprint()]
  await enrichGround(features, 'new', async () => ({ heights: [null, -9999], source: { fileSignature: 'new' } }))
  expect(features.map(f => f.z)).toEqual([undefined, undefined])
  expect(features.map(f => f.h)).toEqual([12, 12])
})

test('one missing datum cannot hide measured and newly repaired neighbours in the same leaf', () => {
  const measured = { ...footprint(93), key: 'measured' }
  const repaired = { ...footprint(101), key: 'repaired' }
  const missing = { ...footprint(), key: 'missing' }
  const result = selectGroundLeaves(new Map([
    ['mixed', [measured, repaired, missing]], ['empty', []], ['missing-only', [missing]],
  ]))
  expect(result?.all.map((f: Footprint) => f.key)).toEqual(['measured', 'repaired'])
  expect(result?.coverage).toEqual(['empty'])
  expect(result?.partialCoverage).toEqual(['mixed'])
  expect(result?.leaves.get('mixed')).toEqual([measured, repaired])
  expect(result?.leaves.get('missing-only')).toEqual([])
  expect(missing.z).toBeUndefined()
})
