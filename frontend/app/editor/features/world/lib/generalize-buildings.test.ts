import { expect, test } from 'bun:test'
import { generalizeBuildings, localProjection, selectLandmarks } from './generalize-buildings'
import type { Footprint } from './building-geometry'

const lon0 = 129.05, lat0 = 35.14, P = localProjection(lon0, lat0)
const kx = Math.cos(lat0 * Math.PI / 180) * 111320
const ll = (x: number, y: number) => [lon0 + x / kx, lat0 + y / 111320]
const box = (key: string, x: number, y: number, w: number, d: number, h: number, z: number, extra: Partial<Footprint> = {}): Footprint =>
  ({ key, pnu: '', s: 'm', h, z, ring: [ll(x, y), ll(x + w, y), ll(x + w, y + d), ll(x, y + d), ll(x, y)], ...extra })

/** A small town: a dense block grid on two terraces, one tower, an L-shaped building, a courtyard building, isolated sheds. */
function town(): Footprint[] {
  const rows: Footprint[] = []
  let n = 0
  for (let i = 0; i < 12; i++) for (let j = 0; j < 12; j++)
    rows.push(box(`ngii:${(n++).toString(16).padStart(64, '0')}/0`, i * 14, j * 14, 10, 10, 6 + ((i * 7 + j * 3) % 9), j < 6 ? 20 : 41.5))
  rows.push(box('tower/0', 60, 60, 30, 30, 140, 20))
  // L shape: its vertex mean lies outside the footprint.
  rows.push({ key: 'ell/0', pnu: '', s: 'm', h: 9, z: 22, ring: [ll(300, 0), ll(360, 0), ll(360, 8), ll(308, 8), ll(308, 60), ll(300, 60), ll(300, 0)] })
  rows.push(box('court/0', 400, 400, 60, 60, 12, 30, { holes: [[ll(415, 415), ll(445, 415), ll(445, 445), ll(415, 445), ll(415, 415)]] }))
  rows.push(box('shed/0', 700, 0, 3, 4, 2.5, 18))
  rows.push(box('shed/1', 900, 900, 5, 5, 3, 19))
  // Diagonal-only contact between two footprints in the same band and ground bin.
  rows.push(box('diag/0', 600, 300, 8, 8, 5, 25), box('diag/1', 608, 308, 8, 8, 5, 25))
  return rows
}

test('every footprint is a landmark or a member of exactly one block', () => {
  const all = town(), r = generalizeBuildings(all, P)
  expect(r.features.length).toBe(r.members.length)
  const seen = new Map<string, number>()
  for (const m of r.members) for (const k of m) seen.set(k, (seen.get(k) ?? 0) + 1)
  expect(seen.size).toBe(all.length)
  for (const f of all) expect(seen.get(f.key)).toBe(1)
  const landmarks = selectLandmarks(all, P)
  // The 140 m tower is alone in its band, but its block outline (8 m raster) would bury the street next to it deeper
  // than E = 16 m: it stays itself. The 6-14 m grid buildings never exceed the budget.
  expect(landmarks.has('tower/0')).toBe(true)
  expect([...landmarks].every(k => k === 'tower/0')).toBe(true)
  r.features.forEach((f, i) => {
    if (f.key.startsWith('lm:')) { expect(r.members[i]).toEqual([f.key.slice(3)]); expect(landmarks.has(f.key.slice(3))).toBe(true) }
    else { expect(f.key.startsWith('blk:')).toBe(true); for (const k of r.members[i]!) expect(landmarks.has(k)).toBe(false) }
  })
  expect(r.stats.landmarks + r.stats.blocks).toBe(r.features.length)
  expect(r.stats.buildings).toBe(all.length)
  expect(r.stats.blocks).toBeLessThan(all.length - r.stats.landmarks)
})

test('blocks sit at member min ground with finite, positive geometry and a non-negative measured error', () => {
  const all = town(), byKey = new Map(all.map(f => [f.key, f])), r = generalizeBuildings(all, P)
  r.features.forEach((f, i) => {
    const mem = r.members[i]!.map(k => byKey.get(k)!)
    if (f.key.startsWith('blk:')) {
      expect(f.z).toBe(Math.min(...mem.map(m => m.z!)))
      const roofs = mem.map(m => m.z! + m.h)
      expect(f.z! + f.h).toBeGreaterThanOrEqual(Math.min(...roofs) - 1e-9)
      expect(f.z! + f.h).toBeLessThanOrEqual(Math.max(...roofs) + 1e-9)
    } else expect([f.z, f.h]).toEqual([mem[0]!.z, mem[0]!.h])
    expect(f.h).toBeGreaterThan(0)
    for (const q of [f.ring, ...(f.holes ?? [])].flat()) expect(q.every(Number.isFinite)).toBe(true)
    expect(f.ring.length).toBeGreaterThanOrEqual(4)
    expect(f.ring[0]).toEqual(f.ring.at(-1)!)
  })
  for (const v of Object.values(r.stats)) expect(Number.isFinite(v)).toBe(true)
  expect(r.stats.geometricError).toBeGreaterThanOrEqual(0)
  expect(r.stats.geometricError).toBe(Math.max(r.stats.hausdorffM, r.stats.verticalMaxM))
  // Closing at eps/2 cells cannot move an outline by more than ~eps plus simplification.
  expect(r.stats.hausdorffM).toBeLessThan(40)
})

test('terraces in different ground bins never merge into one block', () => {
  const r = generalizeBuildings(town(), P)
  r.features.forEach((f, i) => {
    if (!f.key.startsWith('blk:')) return
    const zs = new Set(r.members[i]!.filter(k => k.startsWith('ngii:')).map(k => Number.parseInt(k.slice(5, 69), 16) % 12 < 6))
    expect(zs.size).toBeLessThanOrEqual(1)
  })
})

test('output is deterministic', () => {
  const a = generalizeBuildings(town(), P), b = generalizeBuildings(town(), P)
  expect(JSON.stringify(b)).toBe(JSON.stringify(a))
  // Input order of unrelated groups does not matter for the member partition.
  const c = generalizeBuildings([...town()].reverse(), P)
  const part = (r: typeof a) => r.members.map(m => [...m].sort().join(',')).sort()
  expect(part(c)).toEqual(part(a))
})

test('the error sees a block covering a lower building of another band, filled courtyards, and the worst cell', () => {
  // Two 40 m buildings with a 4 m house in the 12 m gap: the closed 40 m block covers the house and the gap floor.
  // True 3D Hausdorff (1 m voxels, terrain included) is 15 m (gap floor to the block's end walls); never underestimated.
  const gap = generalizeBuildings([box('A', 0, 0, 30, 30, 40, 20), box('B', 42, 0, 30, 30, 40, 20), box('low', 32, 5, 8, 8, 4, 20)], P, 16, new Set())
  expect(gap.stats.verticalMaxM).toBeGreaterThanOrEqual(15)
  expect(gap.stats.verticalMaxM).toBeLessThan(36) // not the hidden house's full roof difference
  expect(gap.stats.geometricError).toBeGreaterThanOrEqual(15)
  // Ground between 10 m-spaced 30-38 m buildings is closed under one block: the gap floor is ~34 m from its roof.
  const filler = Array.from({ length: 40 }, (_, i) => box(`f${i}`, 1000 + (i % 8) * 30, 1000 + Math.floor(i / 8) * 30, 20, 20, 30 + (i % 5) * 2, 20))
  expect(generalizeBuildings(filler, P, 16, new Set()).stats.verticalMaxM).toBeGreaterThanOrEqual(30)
  // A 50 x 50 courtyard inside an 80 x 80 building is filled by the block: the original has no cells there (true 3D: 12 m).
  const court = generalizeBuildings([box('court', 0, 0, 80, 80, 12, 20, { holes: [[ll(15, 15), ll(65, 15), ll(65, 65), ll(15, 65), ll(15, 15)]] }),
    box('x', 200, 0, 10, 10, 12, 20)], P, 16, new Set())
  expect(court.features.every(f => !f.holes?.length)).toBe(true)
  expect(court.stats.hausdorffM).toBeGreaterThanOrEqual(25)
  expect(court.stats.verticalMaxM).toBe(12)
  // An unchanged landmark has no error beyond quantization.
  const exact = generalizeBuildings([box('only', 0, 0, 20, 20, 30, 20)], P, 16, new Set(['only']))
  expect(exact.stats.verticalMaxM).toBe(0)
  expect(exact.stats.hausdorffM).toBeLessThanOrEqual(2)
})

test('a landmark is drawn as its box only when the box deviation fits the level error, whatever its height', () => {
  // Corner-cut 30 x 30 footprint: a 3 m cut moves the box ~2 m from the footprint, next to the same roof.
  const cut = (key: string, x: number, h: number, c: number): Footprint => ({ key, pnu: '', s: 'm', h, z: 20, ring: [ll(x, 0), ll(x + 30 - c, 0), ll(x + 30, c), ll(x + 30, 30), ll(x, 30), ll(x, 0)] })
  const sheds = Array.from({ length: 6 }, (_, i) => box(`s${i}`, 300 + i * 6, 300, 4, 4, 3, 20))
  for (const h of [150, 4]) {
    const small = generalizeBuildings([cut('t', 0, h, 3), ...sheds], P, 16, new Set(['t']))
    expect(small.stats.landmarksObb).toBe(1)
    expect(small.features.find(f => f.key === 'lm:t')!.ring.length).toBe(5)
    expect(small.stats.verticalMaxM).toBeLessThan(6) // not the landmark's height
    // A 15 m cut (box ~11 m off the footprint) exceeds this level's ~8 m error: the footprint is kept.
    const big = generalizeBuildings([cut('t', 0, h, 15), ...sheds], P, 16, new Set(['t']))
    expect(big.stats.landmarksObb).toBe(0)
    expect(big.stats.geometricError).toBeLessThan(10)
  }
})

test('landmarks: only buildings a merge would misrepresent beyond the level budget, capped per bin', () => {
  // A row of 15 m buildings with one 27.9 m member (same band): ~11.6 m above the block roof.
  const row = Array.from({ length: 10 }, (_, i) => box(`r${i}`, i * 14, 0, 12, 12, i === 4 ? 27.9 : 15, 20))
  expect([...selectLandmarks(row, P, 16)]).toEqual(['r4']) // > eps/2 = 8 m
  expect(selectLandmarks(row, P, 64).size).toBe(0) // < 32 m: the root level's budget absorbs it
  // Rural: a 6.8 m house among 4 m houses is never a landmark (no relative top-n rule).
  const rural = Array.from({ length: 30 }, (_, i) => box(`h${i}`, (i % 6) * 12, Math.floor(i / 6) * 12, 9, 9, i === 7 ? 6.8 : 4, 30))
  expect(selectLandmarks(rural, P, 16).size).toBe(0)
  // Fifty 27.9 m buildings closed with fifty 14.5 m ones into one ~21 m slab burying its ground: all fifty exceed
  // E = 16 m, at most 32 per (8 eps)^2 bin are kept.
  const dense = Array.from({ length: 100 }, (_, i) => box(`d${i}`, (i % 10) * 11, Math.floor(i / 10) * 11, 10, 10, i % 2 === 0 ? 27.9 : 14.5, 20))
  expect(selectLandmarks(dense, P, 16).size).toBe(32)
})

test('invalid input is rejected', () => {
  expect(() => generalizeBuildings([], P)).toThrow('Invalid generalization input')
  expect(() => generalizeBuildings([box('a/0', 0, 0, 5, 5, 3, Number.NaN)], P)).toThrow('Invalid footprint')
  expect(() => generalizeBuildings([box('a/0', 0, 0, 5, 5, 3, 1), box('a/0', 9, 0, 5, 5, 3, 1)], P)).toThrow('Duplicate')
})
