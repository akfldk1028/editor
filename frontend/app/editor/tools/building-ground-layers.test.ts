import { expect, test } from 'bun:test'
import { canResumeLayeredGround, enrichLayeredGround, layeredGroundRevision, type GroundLayer } from './building-ground-layers'
import type { Footprint } from '../features/world/lib/building-geometry'

const footprint = (z?: number): Footprint => ({ key: 'b', pnu: '', ring: [[127, 37]], h: 12, s: 'm', z })
const layer = (revision: string, heights: (number | null)[]): GroundLayer => ({
  revision, sample: async () => ({ heights, source: { fileSignature: revision } }),
})

test('base fills missing, precision overrides finite base, and precision NoData preserves base', async () => {
  const features = [footprint(), footprint(93), footprint(), footprint(), footprint(50)]
  const result = await enrichLayeredGround(features, {
    base: layer('base', [10, 20, null]), precise: layer('precise', [11, 94, null, null, -9999]),
  })
  expect(features.map(f => f.z)).toEqual([11, 94, 20, undefined, 50])
  expect(features.every(f => f.h === 12 && f.s === 'm')).toBe(true)
  expect(result.metrics).toEqual({ beforeMissing: 3, newlyFilled: 2, preciseOverride: 2, remaining: 1 })
  expect(result.assignments).toEqual(['precise', 'precise', 'base', 'missing', 'existing'])
  expect(result.sources.base?.fileSignature).toBe('base')
  expect(result.sources.precise?.fileSignature).toBe('precise')
})

test('precision alone fills missing ground and valid zero is preserved without fabrication', async () => {
  const features = [footprint(), footprint(), footprint(22)]
  const result = await enrichLayeredGround(features, { precise: layer('precise', [0, null, null]) })
  expect(features.map(f => f.z)).toEqual([0, undefined, 22])
  expect(result.metrics).toEqual({ beforeMissing: 2, newlyFilled: 1, preciseOverride: 0, remaining: 1 })
})

test('a mixed revision in a later batch leaves the entire feature set unchanged', async () => {
  const features = Array.from({ length: 1025 }, () => footprint(1))
  let calls = 0
  await expect(enrichLayeredGround(features, { precise: {
    revision: 'first', sample: async points => ({ heights: points.map(() => 20),
      source: { fileSignature: ++calls === 1 ? 'first' : 'second' } }),
  } })).rejects.toThrow('source changed')
  expect(features.every(f => f.z === 1)).toBe(true)
})

test('final source verification failure also rolls back already staged base fills', async () => {
  const features = [footprint()]
  await expect(enrichLayeredGround(features, {
    base: { ...layer('base', [10]), verify: async () => { throw new Error('source changed') } },
    precise: layer('precise', [11]),
  })).rejects.toThrow('source changed')
  expect(features[0]!.z).toBeUndefined()
})

test('invalid result length does not partially apply base samples', async () => {
  const features = [footprint()]
  await expect(enrichLayeredGround(features, { base: layer('base', [10]), precise: layer('p', []) }))
    .rejects.toThrow('Invalid DEM result')
  expect(features[0]!.z).toBeUndefined()
})

test('paired revision depends on layer priority and both sources', () => {
  expect(layeredGroundRevision({ base: 'a', precise: 'b' })).not.toBe(layeredGroundRevision({ base: 'b', precise: 'a' }))
  expect(layeredGroundRevision({ base: 'a', precise: 'b' })).not.toBe(layeredGroundRevision({ base: 'a', precise: 'c' }))
  expect(layeredGroundRevision({ base: 'a' })).not.toBe(layeredGroundRevision({ precise: 'a' }))
})

test('layered resume cannot skip archive or previous precision revisions', () => {
  expect(canResumeLayeredGround({ groundPolicy: 'archive' }, 'new')).toBe(false)
  expect(canResumeLayeredGround({ groundPolicy: 'local-dem', groundRevision: 'new' }, 'new')).toBe(false)
  expect(canResumeLayeredGround({ groundPolicy: 'layered-ground-v1', groundRevision: 'old' }, 'new')).toBe(false)
  expect(canResumeLayeredGround({ groundPolicy: 'layered-ground-v1', groundRevision: 'new' }, 'new')).toBe(true)
})
