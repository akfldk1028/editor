import { expect, test } from 'bun:test'
import { createTerrainHeightContract, supportedGridHeight } from './terrain-height-contract'

const policy = { archiveSha256: 'a'.repeat(64), minLevel: 0, maxLevel: 2, size: 3 }
const key = { level: 2, x: 0, y: 0 }

test('finite bilinear weights cannot borrow zero-weight support at an empty exact vertex', () => {
  const grid = new Float32Array(9).fill(80); grid[0] = NaN
  expect(supportedGridHeight(grid, 0, 0, 3)).toBeUndefined()
  expect(supportedGridHeight(grid, 1e-13, 0, 3)).toBe(80)
  expect(supportedGridHeight(grid, 0.5, 0.5, 3)).toBe(80)
})

test('present NoData vertices resolve explicit ancestors and display/sample share the resolved surface', async () => {
  const fine = new Float32Array(9).fill(80); fine[0] = NaN
  const contract = createTerrainHeightContract(async k => k.level === 2 ? fine : new Float32Array(9).fill(20), policy)
  const grid = await contract.resolve(key)
  expect(grid.heights[0]).toBe(20); expect(grid.sourceLevels[0]).toBe(1)
  expect(grid.sourceLevels[1]).toBe(2)
  expect(contract.sample(grid, 0.5, 0.5)).toBe(65)
  expect(supportedGridHeight(fine, 0.5, 0.5, 3)).toBe(80)
})

test('missing and all-NoData ancestors produce explicit zero only after every read succeeds', async () => {
  const calls: number[] = []
  const contract = createTerrainHeightContract(async k => { calls.push(k.level); return k.level === 1 ? new Float32Array(9).fill(NaN) : null }, policy)
  const grid = await contract.resolve(key)
  expect(calls).toEqual([2,1,0]); expect(grid.heights.every(x => x === 0)).toBe(true)
  expect(grid.sourceLevels.every(x => x === -1)).toBe(true)
})

test('failed read is not cached as zero and retry can recover', async () => {
  let fail = true
  const contract = createTerrainHeightContract(async () => { if (fail) throw Error('network'); return new Float32Array(9).fill(70) }, policy)
  await expect(contract.resolve(key)).rejects.toThrow('network')
  fail = false
  expect((await contract.resolve(key)).heights[0]).toBe(70)
})

test('camera order and cache eviction cannot alter resolved vertices', async () => {
  const raw = async (k: { level: number }) => k.level === 2 ? null : new Float32Array([1,2,3,4,5,6,7,8,9])
  const contract = createTerrainHeightContract(raw, { ...policy, keep: 1 })
  const first = await contract.resolve(key)
  await contract.resolve({ level: 1, x: 1, y: 0 })
  expect(Array.from((await contract.resolve(key)).heights)).toEqual(Array.from(first.heights))
  const other = createTerrainHeightContract(raw, { ...policy, archiveSha256: 'b'.repeat(64) })
  expect(other.identity).not.toBe(contract.identity)
  expect(() => other.sample(first, 0, 0)).toThrow('Mismatched')
})
