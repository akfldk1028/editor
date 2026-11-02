import { expect, test } from 'bun:test'
import { enrichComposedGround } from './building-composed-ground'
import type { Footprint } from '../features/world/lib/building-geometry'

const f = (key: string, z?: number): Footprint => ({ key, pnu: 'p', ring: [[127, 37]], holes: [[[127.1, 37.1]]], h: 10, s: 'm', z })
const layer = (heights: (number | null)[]) => ({ revision: 'composed', sample: async () => ({ heights, source: { fileSignature: 'composed' } }) })
const fallback = { archiveSHA256: 'a'.repeat(64), contract: 'resolved-ancestor-grid-v1', records: [{ key: 'b', point: [127, 37], height: 31, sourceLevels: [16], ellipsoidZero: false }] }

test('composed finite sample overrides inherited finite z; only verified archive evidence fills native NoData', async () => {
  const rows = [f('a', 90), f('b', 91), f('c', 92), f('d')]
  const result = await enrichComposedGround(rows, layer([12, null, null, 0]), fallback)
  expect(rows.map(r => r.z)).toEqual([12, 31, undefined, 0])
  expect(result.assignments).toEqual(['composed', 'archive-ancestor', 'missing', 'composed'])
  expect(rows[0]!.holes).toEqual([[[127.1, 37.1]]])
  expect(rows.map(r => [r.h, r.s])).toEqual([[10, 'm'], [10, 'm'], [10, 'm'], [10, 'm']])
})
test('fallback point mismatch or confirmed ellipsoid zero cannot become supported ground', async () => {
  await expect(enrichComposedGround([f('b')], layer([null]), { ...fallback, records: [{ ...fallback.records[0]!, point: [128, 37] }] })).rejects.toThrow('anchor')
  await expect(enrichComposedGround([f('b')], layer([null]), { ...fallback, records: [{ ...fallback.records[0]!, ellipsoidZero: true }] })).rejects.toThrow('unsupported')
})
test('source changes are atomic and fallback never overrides valid native sample', async () => {
  const rows = [f('b', 99)]
  await expect(enrichComposedGround(rows, { ...layer([7]), verify: async () => { throw Error('changed') } }, fallback)).rejects.toThrow('changed')
  expect(rows[0]!.z).toBe(99)
  await enrichComposedGround(rows, layer([7]), fallback)
  expect(rows[0]!.z).toBe(7)
})
