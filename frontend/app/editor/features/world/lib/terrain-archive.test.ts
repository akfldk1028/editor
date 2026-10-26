import { expect, test } from 'bun:test'
import { decodeHeightTile, createTerrainArchiveReader } from './terrain-archive'

function tile(value: number) {
  const b = new ArrayBuffer(8 + 1089 * 4), v = new DataView(b)
  new Uint8Array(b).set([72, 84, 77, 49]); v.setUint16(4, 33, true)
  for (let i = 0; i < 1089; i++) v.setFloat32(8 + i * 4, value, true)
  return b
}
const metadata = { schema: 'ngii-heightmap-v1', size: 33, grid: 'Cesium.GeographicTilingScheme',
  archiveZoomOffset: 1, minLevel: 11, maxLevel: 17, vrt_sha256: 'a'.repeat(64) }

for (const mode of ['read', 'raw'] as const) test(`${mode}: more than2000 pending keys never evict in-flight deduplication`, async () => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let firstCalls = 0, active = 0, maximum = 0
  const reader = createTerrainArchiveReader('https://tiles.example/pending.pmtiles', undefined, () => ({
    getMetadata: async () => ({ ...metadata, minLevel: 20, maxLevel: 20 }),
    getZxy: async (_z, x) => { if (x === 0) firstCalls++; active++; maximum = Math.max(maximum, active); await gate; active--; return { data: tile(0) } },
  }))
  const read = mode === 'raw' ? reader.raw : reader
  const jobs = Array.from({ length: 2001 }, (_, i) => read(`20/${i}/0`))
  await new Promise(resolve => setTimeout(resolve, 0))
  jobs.push(read('20/0/0'))
  await new Promise(resolve => setTimeout(resolve, 0))
  release()
  const results = await Promise.all(jobs)
  expect(firstCalls).toBe(1)
  expect(maximum).toBe(8)
  expect(results[0]).toBe(results.at(-1))
})

for (const mode of ['read', 'raw'] as const) test(`${mode}: settled LRU stays bounded and failures remain retryable`, async () => {
  const calls = new Map<number, number>()
  let fail = true
  const reader = createTerrainArchiveReader('https://tiles.example/lru.pmtiles', undefined, () => ({
    getMetadata: async () => ({ ...metadata, minLevel: 20, maxLevel: 20 }),
    getZxy: async (_z, x) => { calls.set(x, (calls.get(x) ?? 0) + 1); if (x === 3000 && fail) { fail = false; throw Error('transient') } return undefined },
  }))
  const read = mode === 'raw' ? reader.raw : reader
  for (let i = 0; i < 2000; i++) expect(await read(`20/${i}/0`)).toBeNull()
  await read('20/0/0'); await read('20/2000/0'); await read('20/0/0'); await read('20/1/0')
  expect(calls.get(0)).toBe(1); expect(calls.get(1)).toBe(2)
  await expect(read('20/3000/0')).rejects.toThrow('transient')
  expect(await read('20/3000/0')).toBeNull(); expect(calls.get(3000)).toBe(2)
})

test('binary height tiles preserve zero and explicit NoData and reject corruption', () => {
  expect(decodeHeightTile(tile(0))[0]).toBe(0)
  expect(Number.isNaN(decodeHeightTile(tile(NaN))[0])).toBe(true)
  expect(() => decodeHeightTile(tile(Infinity))).toThrow()
  expect(() => decodeHeightTile(new ArrayBuffer(8))).toThrow()
})

test('external archive maps geographic level to square PMTiles index and shares metadata', async () => {
  const calls: number[][] = []; let opens = 0
  const read = createTerrainArchiveReader('https://tiles.example/terrain.pmtiles', undefined, url => {
    expect(url).toBe('https://tiles.example/terrain.pmtiles'); opens++
    return { getMetadata: async () => metadata, getZxy: async (z,x,y) => { calls.push([z,x,y]); return { data: tile(42) } } }
  })
  const [a,b] = await Promise.all([read('15/55907/9515'),read('15/55907/9515')])
  expect(a?.heights[0]).toBe(42); expect(b?.sourceLevel).toBe(15)
  expect(opens).toBe(1); expect(calls).toEqual([[16,55907,9515]])
})

test('missing detail resamples an available ancestor and never calls a height API', async () => {
  const read = createTerrainArchiveReader('https://tiles.example/a.pmtiles', undefined, () => ({
    getMetadata: async () => metadata,
    getZxy: async z => z === 16 ? { data: tile(81) } : undefined,
  }))
  const result = await read('17/223628/38060')
  expect(result?.sourceLevel).toBe(15); expect(result?.heights[1088]).toBe(81)
})

test('explicit empty measured tiles never borrow finite parent ground', async () => {
  const calls: number[] = []
  const read = createTerrainArchiveReader('https://tiles.example/a.pmtiles', undefined, () => ({
    getMetadata: async () => metadata,
    getZxy: async z => { calls.push(z); return { data: tile(z === 18 ? NaN : 81) } },
  }))
  const result = await read('17/223628/38060')
  expect(result?.sourceLevel).toBe(17)
  expect(result?.heights.every(Number.isNaN)).toBe(true)
  expect(calls).toEqual([18])
})

test('raw contract reads never implicitly resample missing children or replace NoData', async () => {
  const calls: number[] = []
  const read = createTerrainArchiveReader('https://tiles.example/raw.pmtiles', undefined, () => ({
    getMetadata: async () => metadata,
    getZxy: async z => { calls.push(z); return z === 18 ? undefined : { data: tile(NaN) } },
  }))
  expect(await read.raw('17/223628/38060')).toBeNull()
  expect(calls).toEqual([18])
  expect((await read.raw('16/111814/19030'))?.heights.every(Number.isNaN)).toBe(true)
})

test('invalid archive provenance fails closed and missing configuration permits legacy path', async () => {
  const absent = createTerrainArchiveReader(undefined, async () => new Response('', { status: 404 }))
  expect(await absent('15/55907/9515')).toBeUndefined()
  const invalid = createTerrainArchiveReader('https://tiles.example/a.pmtiles', undefined, () => ({
    getMetadata: async () => ({ ...metadata, grid: 'WebMercator' }), getZxy: async () => ({ data: tile(1) }),
  }))
  await expect(invalid('15/55907/9515')).rejects.toThrow('terrain archive metadata')
})

test('a regional archive preserves legacy coverage elsewhere and bounds network concurrency', async () => {
  let running=0, maximum=0
  const read=createTerrainArchiveReader('https://tiles.example/a.pmtiles',undefined,()=>({
    getMetadata:async()=>({...metadata,bounds:[127,37,128,38]}),
    getZxy:async()=>{running++;maximum=Math.max(maximum,running);await new Promise(r=>setTimeout(r,1));running--;return {data:tile(40)}},
  }))
  expect(await read('15/50000/9000')).toBeUndefined()
  await Promise.all(Array.from({length:20},(_,i)=>read(`15/${55900+i}/9515`)))
  expect(maximum).toBe(8)
})

test('a transient manifest failure is retried instead of permanently enabling computation fallback', async () => {
  let attempts=0
  const read=createTerrainArchiveReader(undefined,async()=>{
    if (++attempts===1) throw new Error('timeout')
    return Response.json({url:'/api/map-data/world-terrain/test.pmtiles',vrt_sha256:metadata.vrt_sha256})
  },()=>({getMetadata:async()=>metadata,getZxy:async()=>({data:tile(18)})}))
  await expect(read('15/55907/9515')).rejects.toThrow('timeout')
  expect((await read('15/55907/9515'))?.heights[0]).toBe(18)
  expect(attempts).toBe(2)
})
