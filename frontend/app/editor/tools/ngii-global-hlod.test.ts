import { expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { gunzipSync, gzipSync } from 'node:zlib'
import { readRegionalHlodLeaf, buildGlobalHlod, occupiedCells, componentCells, rigidInverse, withAggregateCounts, type RegionInput, type HlodIO } from './ngii-global-hlod'
import { bakeMesh, earth, frame, meshFootprintBounds } from '../features/world/lib/prebuilt-mesh'
import { tileXY, type Footprint } from '../features/world/lib/building-geometry'
const multiply = (a: number[], b: number[]) => Array.from({ length: 16 }, (_, i) => [0, 1, 2, 3].reduce((s, k) => s + a[k * 4 + i % 4]! * b[Math.floor(i / 4) * 4 + k]!, 0))
const point = (m: number[], p: number[]) => [0, 1, 2].map(r => m[12 + r]! + p.reduce((s, v, c) => s + v * m[c * 4 + r]!, 0))
const decode = (bytes: Uint8Array) => JSON.parse(new TextDecoder().decode(bytes))
const feature = (lon: number, lat: number, index: number, component = 0): Footprint => ({ key: `ngii:${index.toString(16).padStart(64, '0')}/${component}`, pnu: '', z: 132, h: 18, s: 'm',
  ring: [[lon, lat], [lon + 0.001, lat], [lon + 0.001, lat + 0.001], [lon, lat + 0.001], [lon, lat]] })

test('absolute ENU external-root transforms compose once, including real ECEF positions', () => {
  const a = frame(127.02, 37.5).transform, b = frame(129.1, 35.2).transform, c = frame(126.9, 37.4).transform
  const composed = multiply(multiply(multiply(multiply(a, rigidInverse(a)), b), rigidInverse(b)), c)
  for (const p of [[0, 0, 0], [135, -320, 79]]) point(composed, p).forEach((v, i) => expect(Math.abs(v - point(c, p)[i]!)).toBeLessThan(1e-7))
  expect(() => rigidInverse(a.map((v, i) => i === 0 ? v * 2 : v))).toThrow()
})

test('occupied cells cap256 while preserving every component and primary building count', () => {
  const rows = Array.from({ length: 1000 }, (_, i) => feature(127 + (i % 40) * 0.0001, 37.5 + Math.floor(i / 40) * 0.0001, i + 1))
  rows.push(feature(127.5, 37.5, 1, 1)) // Full component crossing its owner's bounds must remain enclosed.
  const cells = occupiedCells(componentCells(rows), '13/6985/3174')
  expect(cells.length).toBeLessThanOrEqual(256)
  expect(cells.reduce((s, c) => s + c.components, 0)).toBe(1001)
  expect(cells.reduce((s, c) => s + c.buildingAnchors, 0)).toBe(1000)
  expect(Math.max(...cells.map(c => c.bounds[2]))).toBeGreaterThan(127.5)
  expect(() => componentCells([rows[0]!, rows[0]!])).toThrow('duplicate')
  expect(() => componentCells([feature(127, 37, 1, 2)])).toThrow('Missing canonical component')
})

test('aggregate B3DM counts preserve original GLB and neutral material byte-for-byte', () => {
  const f = feature(127, 37, 1), cells = componentCells([f]), raw = bakeMesh([f], frame(127, 37), false), output = withAggregateCounts(raw, cells)
  const split = (bytes: Uint8Array) => { const h = new DataView(bytes.buffer); const ft = h.getUint32(12, true), bt = h.getUint32(20, true); return { table: decode(bytes.subarray(28 + ft, 28 + ft + bt)), glb: bytes.subarray(28 + ft + bt) } }
  expect(split(output).table.componentCount).toEqual([1])
  expect(split(output).table.buildingAnchorCount).toEqual([1])
  expect(split(output).glb).toEqual(split(raw).glb)
})

test('external quadtree retains renderable parents, all leaves, bounds, counts, and readback hashes', async () => {
  const features = [feature(127.01, 37.5, 1), feature(127.06, 37.5, 2), feature(129.1, 35.2, 3), feature(126.5, 33.5, 4)]
  const regions: RegionInput[] = features.map((f, i) => ({ owner: `14/${tileXY(f.ring[0]![0]!, f.ring[0]![1]!, 14).join('/')}`, uri: `regions/${i}/tileset.json`, folder: String(i) }))
  const files = new Map<string, Uint8Array>()
  const io: HlodIO = { write: async (p, b) => { if (files.has(p)) throw Error('Overwrite'); files.set(p, b) }, read: async p => files.get(p)!, leaf: async r => {
    const f = features[Number(r.folder)]!; return { features: [f], error: 30, bounds: meshFootprintBounds(f), low: -12, high: 151 }
  } }
  const result = await buildGlobalHlod(regions, io)
  expect(result.assetPacking).toBe('gzip6-mesh-and-metadata-v1')
  expect(result.components).toBe(4); expect(result.buildings).toBe(4); expect(result.regions).toBe(4)
  expect(files.get('tileset.json')!.length).toBeLessThan(1500)
  const leafURIs: string[] = []
  for (const [path, bytes] of files) if (path.startsWith('nodes/') && path.endsWith('.json')) {
    const root = decode(bytes).root
    expect(root.refine).toBe('REPLACE'); expect(root.children.length).toBeLessThanOrEqual(4)
    expect(root.extras.occupiedCells).toBeLessThanOrEqual(256)
    expect(files.has(`nodes/${root.content.uri}`)).toBe(true)
    expect(root.content.uri.endsWith('.b3dm.gz')).toBe(true)
    const packed = files.get(`nodes/${root.content.uri}`)!, mesh = gunzipSync(packed)
    expect(packed).toEqual(new Uint8Array(gzipSync(mesh, { level: 6 })))
    const header = new DataView(mesh.buffer, mesh.byteOffset, mesh.byteLength)
    expect(header.getUint32(0, true)).toBe(0x6d643362)
    expect(header.getUint32(8, true)).toBe(mesh.length)
    const ft = header.getUint32(12, true), bt = header.getUint32(20, true)
    const table = decode(mesh.subarray(28 + ft, 28 + ft + bt))
    expect(table.componentCount.reduce((a: number, b: number) => a + b, 0)).toBe(root.extras.components)
    expect(table.buildingAnchorCount.reduce((a: number, b: number) => a + b, 0)).toBe(root.extras.buildings)
    const cells = decode(files.get(path.replace('nodes/', 'summaries/'))!)
    const bounds = [Math.min(...cells.map((c: any) => c.bounds[0])), Math.min(...cells.map((c: any) => c.bounds[1])),
      Math.max(...cells.map((c: any) => c.bounds[2])), Math.max(...cells.map((c: any) => c.bounds[3]))]
    const origin = frame((bounds[0]! + bounds[2]!) / 2, (bounds[1]! + bounds[3]!) / 2)
    const key = path.slice('nodes/'.length, -'.json'.length).replaceAll('-', '/')
    const original: Footprint[] = cells.map((c: any, i: number) => ({ key: `${key}:${i}`, pnu: '', s: 'u', z: c.ground, h: c.roof - c.ground,
      ring: [[c.bounds[0], c.bounds[1]], [c.bounds[2], c.bounds[1]], [c.bounds[2], c.bounds[3]], [c.bounds[0], c.bounds[3]], [c.bounds[0], c.bounds[1]]] }))
    expect(root.transform).toEqual(origin.transform)
    expect(new Uint8Array(mesh)).toEqual(new Uint8Array(withAggregateCounts(bakeMesh(original, origin, false), cells)))
    expect(bytes.length).toBeLessThan(6000)
    const center = point(root.transform, [0, 0, 0]), radius = root.boundingVolume.sphere[3]
    for (const child of root.children) {
      expect(root.geometricError).toBeGreaterThan(child.geometricError)
      const world = point(multiply(root.transform, child.transform), child.boundingVolume.sphere.slice(0, 3))
      expect(Math.hypot(...world.map((v, i) => v - center[i]!)) + child.boundingVolume.sphere[3]).toBeLessThanOrEqual(radius + 1e-7)
      if (child.content.uri.startsWith('../regions/')) leafURIs.push(child.content.uri)
    }
  }
  expect(leafURIs.sort()).toEqual(regions.map(r => `../${r.uri}`).sort())
  for (const file of result.files) {
    const bytes = files.get(file.path)!
    expect(createHash('sha256').update(bytes).digest('hex')).toBe(file.sha256)
    expect(file.bytes).toBe(bytes.length)
    if (file.path.endsWith('.gz')) {
      const decoded = gunzipSync(bytes)
      expect(file.contentEncoding).toBe('gzip')
      expect(file.decodedBytes).toBe(decoded.length)
      expect(file.decodedSHA256).toBe(createHash('sha256').update(decoded).digest('hex'))
    }
  }
  const sphere = decode(files.get('tileset.json')!).root.boundingVolume.sphere
  for (const f of features) for (const p of f.ring) for (const h of [-12, f.z! + f.h]) {
    const world = earth(p[0]!, p[1]!, h)
    expect(Math.hypot(...world.map((v, i) => v - sphere[i]!))).toBeLessThan(sphere[3])
  }
  const repeated = new Map<string, Uint8Array>()
  const repeat = await buildGlobalHlod(regions, { ...io, write: async (p, b) => { repeated.set(p, b) }, read: async p => repeated.get(p)! })
  expect(repeat.files).toEqual(result.files)
  for (const [name, bytes] of repeated) expect(bytes).toEqual(files.get(name)!)
})

test('failed readback is never published as a successful hierarchy', async () => {
  const f = feature(127, 37, 1)
  await expect(buildGlobalHlod([{ owner: '14/13971/6377', uri: 'region/tileset.json', folder: '' }], {
    write: async () => {}, read: async () => new Uint8Array(), leaf: async () => ({ features: [f], error: 10, bounds: meshFootprintBounds(f), low: -12, high: 151 }),
  })).rejects.toThrow('readback mismatch')
})

test('corrupt gzip storage is rejected before a hierarchy receipt is returned', async () => {
  const f = feature(127, 37, 1), files = new Map<string, Uint8Array>()
  await expect(buildGlobalHlod([{ owner: '14/13971/6377', uri: 'region/tileset.json', folder: '' }], {
    write: async (name, bytes) => { const bad = bytes.slice(); if (name.endsWith('.gz')) bad[bad.length - 8] = bad[bad.length - 8]! ^ 1; files.set(name, bad) },
    read: async name => files.get(name)!, leaf: async () => ({ features: [f], error: 10, bounds: meshFootprintBounds(f), low: -12, high: 151 }),
  })).rejects.toThrow('readback mismatch')
  expect(files.has('tileset.json')).toBe(false)
  expect(() => gunzipSync([...files.values()][0]!)).toThrow()
})

function packedLeafFixture() {
  const features = [feature(127, 37, 1)], bounds = meshFootprintBounds(features[0]!)
  const origin = frame((bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2)
  const files = new Map<string, Uint8Array>(), rows: any[] = []
  const put = (name: string, value: unknown, zipped: boolean) => {
    const decoded = new TextEncoder().encode(typeof value === 'string' ? value : JSON.stringify(value))
    const bytes = zipped ? new Uint8Array(gzipSync(decoded, {level:6})) : decoded
    files.set(name, bytes)
    const row = {path:name,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),
      ...(zipped ? {contentEncoding:'gzip',decodedBytes:decoded.length,decodedSHA256:createHash('sha256').update(decoded).digest('hex')} : {})}
    const old=rows.findIndex(r=>r.path===name);if(old>=0)rows.splice(old,1);rows.push(row)
  }
  const tileset = {root:{transform:origin.transform,geometricError:30,boundingVolume:{region:[...bounds.map(v=>v*Math.PI/180),-13,151]}}}
  put('footprints.json.gz',features,true);put('tileset.json',tileset,false)
  const receipt = {assetPacking:'gzip6-mesh-and-metadata-v1',components:1,buildings:1,bounds,files:rows}
  return {features,files,receipt,tileset,put,load:()=>readRegionalHlodLeaf(receipt,async name=>files.get(name)!)}
}

test('regional gzip metadata restores identical footprints and retains frame and bounds validation', async () => {
  const f=packedLeafFixture(),leaf=await f.load()
  expect(leaf.features).toEqual(f.features);expect(leaf.low).toBe(-13);expect(leaf.high).toBe(151)
  f.tileset.root.boundingVolume.region[5]=100;f.put('tileset.json',f.tileset,false)
  await expect(f.load()).rejects.toThrow('bounds omit')
})

test('regional metadata rejects incompatible packing, corruption, hash and coverage mismatches', async () => {
  for(const change of [
    (f:ReturnType<typeof packedLeafFixture>)=>{f.receipt.assetPacking='gzip6-sha256-identical-b3dm-v1'},
    (f:ReturnType<typeof packedLeafFixture>)=>{f.receipt.files[0].sha256='0'.repeat(64)},
    (f:ReturnType<typeof packedLeafFixture>)=>{f.receipt.files[0].decodedSHA256='0'.repeat(64)},
    (f:ReturnType<typeof packedLeafFixture>)=>{f.receipt.files[0].decodedBytes++},
    (f:ReturnType<typeof packedLeafFixture>)=>{delete f.receipt.files[0].contentEncoding},
    (f:ReturnType<typeof packedLeafFixture>)=>{f.receipt.components=2},
    (f:ReturnType<typeof packedLeafFixture>)=>{f.tileset.root.boundingVolume.region[0]=NaN;f.put('tileset.json',f.tileset,false)},
    (f:ReturnType<typeof packedLeafFixture>)=>{f.put('footprints.json.gz','invalid json',true)},
    (f:ReturnType<typeof packedLeafFixture>)=>{f.put('footprints.json.gz',{},true)},
    (f:ReturnType<typeof packedLeafFixture>)=>{const bytes=f.files.get('footprints.json.gz')!;bytes[bytes.length-8]=bytes[bytes.length-8]!^1;f.receipt.files[0].sha256=createHash('sha256').update(bytes).digest('hex')},
    (f:ReturnType<typeof packedLeafFixture>)=>{f.tileset.root.transform[12]!+=10;f.put('tileset.json',f.tileset,false)},
  ]) { const f=packedLeafFixture();change(f);await expect(f.load()).rejects.toThrow() }
})
