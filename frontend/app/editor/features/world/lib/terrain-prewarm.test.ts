import { expect, test } from 'bun:test'
import { prewarmTerrainAt } from './terrain-prewarm'
import { createTerrainArchiveReader } from './terrain-archive'

test('prewarms the same geographic level-20 tile sampled for the selected parcel', async () => {
  const keys: string[] = [], order: string[] = []
  const read = Object.assign(async (key: string) => { order.push('tile'); keys.push(key) },
    { prepare: async () => { order.push('metadata') } })
  await prewarmTerrainAt([127.108438, 37.730604], () => true, read)
  expect(order).toEqual(['metadata', 'tile'])
  const [, x, y] = keys[0]!.split('/').map(Number)
  const width = 180 / 2 ** 20
  expect(keys[0]!.startsWith('20/')).toBe(true)
  expect(x! * width - 180).toBeLessThanOrEqual(127.108438)
  expect((x! + 1) * width - 180).toBeGreaterThan(127.108438)
  expect(90 - y! * width).toBeGreaterThanOrEqual(37.730604)
  expect(90 - (y! + 1) * width).toBeLessThan(37.730604)
})

test('a replaced view never dispatches its tile after delayed metadata', async () => {
  let done!: () => void, live = true, reads = 0
  const metadata = new Promise<void>(resolve => { done = resolve })
  const read = Object.assign(async () => { reads++ }, { prepare: () => metadata })
  const task = prewarmTerrainAt([127, 37], () => live, read)
  live = false; done(); await task
  expect(reads).toBe(0)
})

test('missing/invalid coordinates and metadata failures cannot block viewer startup', async () => {
  let reads = 0
  const read = Object.assign(async () => { reads++ }, { prepare: async () => { throw Error('offline') } })
  await prewarmTerrainAt(undefined, () => true, read)
  await prewarmTerrainAt([NaN, 37], () => true, read)
  await prewarmTerrainAt([127, 37], () => true, read)
  expect(reads).toBe(0)
})

test('contract sampling reuses the prewarmed raw ancestor chain without a second request', async () => {
  let requests = 0
  const bytes = new ArrayBuffer(4364), view = new DataView(bytes)
  view.setUint32(0, 0x314d5448, true); view.setUint16(4, 33, true)
  for (let i = 0; i < 1089; i++) view.setFloat32(8 + i * 4, 123, true)
  const read = createTerrainArchiveReader('https://tiles.example/terrain.pmtiles', undefined, () => ({
    getMetadata: async () => ({ schema: 'ngii-heightmap-v1', size: 33, grid: 'Cesium.GeographicTilingScheme',
      archiveZoomOffset: 1, minLevel: 11, maxLevel: 20, vrt_sha256: 'a'.repeat(64) }),
    getZxy: async () => { requests++; return { data: bytes } },
  }))
  const location = [127.108438, 37.730604] as const, width = 180 / 2 ** 20
  await prewarmTerrainAt(location, () => true, read)
  expect(requests).toBe(10) // levels 20..11, requested together
  const x = Math.floor((location[0] + 180) / width), y = Math.floor((90 - location[1]) / width)
  for (let i = 0; i <= 9; i++) expect((await read.raw(`${20 - i}/${Math.floor(x / 2 ** i)}/${Math.floor(y / 2 ** i)}`))?.heights[0]).toBe(123)
  expect(requests).toBe(10)
})
