import { expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { gunzipSync, gzipSync } from 'node:zlib'
import { mkdtemp, readFile, writeFile, stat, rm, mkdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { openHlodOutput, readRegionalHlodLeaf, buildGlobalHlod, generalizeNode, componentItems, landmarkOrder, bucketOf, nodeWidth, multiply, HLOD_TARGET_GZ, HLOD_CHILD_ERROR_CAP, HLOD_EPS_DIVISOR, HLOD_MIN_COVERAGE, HLOD_CONTENT_MIN_LEVEL, HLOD_EMPTY_ERROR_DIVISOR, LOD_CODE_SHA256, rigidInverse, withAggregateCounts, type RegionInput, type HlodIO } from './ngii-global-hlod'
import { bakeMesh, earth, frame, meshFootprintBounds } from '../features/world/lib/prebuilt-mesh'
import { tileXY, type Footprint } from '../features/world/lib/building-geometry'
const parentOf = (key: string) => { const [z, x, y] = key.split('/').map(Number); return `${z! - 1}/${Math.floor(x! / 2)}/${Math.floor(y! / 2)}` }
const point = (m: number[], p: number[]) => [0, 1, 2].map(r => m[12 + r]! + p.reduce((s, v, c) => s + v * m[c * 4 + r]!, 0))
const decode = (bytes: Uint8Array) => JSON.parse(new TextDecoder().decode(bytes))
const feature = (lon: number, lat: number, index: number, component = 0): Footprint => ({ key: `ngii:${index.toString(16).padStart(64, '0')}/${component}`, pnu: '', z: 132, h: 18, s: 'm',
  ring: [[lon, lat], [lon + 0.001, lat], [lon + 0.001, lat + 0.001], [lon, lat + 0.001], [lon, lat]] })

test('HLOD resumes a storage interruption without rewriting completed payloads or changing hierarchy bytes', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'hlod-resume-')), identity = { source: 'a'.repeat(64), terrain: 'b'.repeat(64) }
  try {
    let writes = 0
    const first = await openHlodOutput(folder, identity, async () => { if (++writes === 4) throw Error('needs_storage') })
    const f = feature(127, 37, 1), regions = [{ owner: '14/13971/6377', uri: '/region/tileset.json', folder: '' }]
    const leaf = async () => ({ features: [f], error: 30, bounds: meshFootprintBounds(f), low: -13, high: 151 })
    await expect(buildGlobalHlod(regions, { ...first, leaf })).rejects.toThrow('needs_storage')
    const completed = join(folder, 'nodes/13-6985-3188.b3dm.gz'), stamp = await stat(completed)
    await expect(stat(join(folder, 'tileset.json'))).rejects.toThrow()
    await mkdir(join(folder, 'summaries'), { recursive: true })
    await writeFile(join(folder, 'summaries/13-6985-3188.json.part'), 'interrupted bytes')
    const resumed = await openHlodOutput(folder, identity, async () => {})
    const result = await buildGlobalHlod(regions, { ...resumed, leaf })
    expect((await stat(completed)).mtimeMs).toBe(stamp.mtimeMs)
    const baseline = new Map<string, Uint8Array>()
    const expected = await buildGlobalHlod(regions, { leaf, write: async (p,b) => { baseline.set(p,b) }, read: async p => baseline.get(p)! })
    expect(result).toEqual(expected)
    for (const [name, bytes] of baseline) expect(new Uint8Array(await resumed.read(name))).toEqual(bytes)
    const receipt = new TextEncoder().encode(JSON.stringify(result))
    await resumed.write('candidate-receipt.json', receipt)
    const receiptStamp = await stat(join(folder, 'candidate-receipt.json'))
    await resumed.write('candidate-receipt.json', receipt)
    expect((await stat(join(folder, 'candidate-receipt.json'))).mtimeMs).toBe(receiptStamp.mtimeMs)
  } finally { await rm(folder, { recursive: true, force: true }) }
})

test('HLOD rejects changed pins, corrupted completed files and unbound directories without overwriting', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'hlod-pin-'))
  try {
    const io = await openHlodOutput(folder, { source: 'a' }, async () => {})
    await io.write('tileset.json', new TextEncoder().encode('original'))
    await expect(openHlodOutput(folder, { source: 'b' }, async () => {})).rejects.toThrow('mismatch')
    await expect(io.write('tileset.json', new TextEncoder().encode('different'))).rejects.toThrow('mismatch')
    expect(await readFile(join(folder, 'tileset.json'), 'utf8')).toBe('original')
    await expect(io.write('../escape.json', new Uint8Array())).rejects.toThrow('path')
    const unbound = join(folder, 'unbound'); await mkdir(unbound); await writeFile(join(unbound, 'tileset.json'), 'old')
    await expect(openHlodOutput(unbound, { source: 'a' }, async () => {})).rejects.toThrow('Unbound')
    const interrupted = join(folder, 'interrupted'); await mkdir(interrupted)
    await writeFile(join(interrupted, 'candidate-inputs.json.part'), 'partial')
    await openHlodOutput(interrupted, { source: 'a' }, async () => {})
    expect(JSON.parse(await readFile(join(interrupted, 'candidate-inputs.json'), 'utf8'))).toEqual({ source: 'a' })
  } finally { await rm(folder, { recursive: true, force: true }) }
})

test('absolute ENU external-root transforms compose once, including real ECEF positions', () => {
  const a = frame(127.02, 37.5).transform, b = frame(129.1, 35.2).transform, c = frame(126.9, 37.4).transform
  const composed = multiply(multiply(multiply(multiply(a, rigidInverse(a)), b), rigidInverse(b)), c)
  for (const p of [[0, 0, 0], [135, -320, 79]]) point(composed, p).forEach((v, i) => expect(Math.abs(v - point(c, p)[i]!)).toBeLessThan(1e-7))
  expect(() => rigidInverse(a.map((v, i) => i === 0 ? v * 2 : v))).toThrow()
})

test('generalized nodes represent every component and primary building exactly once, within the byte target', () => {
  const rows = Array.from({ length: 1000 }, (_, i) => feature(127 + (i % 40) * 0.0001, 37.5 + Math.floor(i / 40) * 0.0001, i + 1))
  rows.push(feature(127.0005, 37.5005, 1, 1))
  const key = '13/6985/3174', node = generalizeNode(componentItems(rows), key)
  expect(node.rows.reduce((s, r) => s + r.components, 0)).toBe(1001)
  expect(node.rows.reduce((s, r) => s + r.buildingAnchors, 0)).toBe(1000)
  expect(node.rows.length).toBeLessThan(100) // merged into blocks, not 1001 boxes
  expect(node.mesh.length).toBeLessThanOrEqual(HLOD_TARGET_GZ)
  expect(node.eps).toBeCloseTo(nodeWidth(key) / HLOD_EPS_DIVISOR, 6)
  expect(node.eps).toBeGreaterThan(110); expect(node.eps).toBeLessThan(130) // ~2x a regional R0 (64 m), not the same coarseness
  expect(node.error).toBeGreaterThan(0)
  for (const r of node.rows) { expect(r.ground).toBe(132); expect(r.roof).toBe(150) }
  expect(() => componentItems([rows[0]!, rows[0]!])).toThrow('duplicate')
  expect(() => componentItems([feature(127, 37, 1, 2)])).toThrow('Missing canonical component')
  expect(() => generalizeNode([...componentItems(rows), ...componentItems([rows[0]!])], key)).toThrow('Duplicate')
})

test('landmarks are tall, prominent and spatially balanced: at most one per bucket, kept as themselves', () => {
  const box = (lon: number, lat: number, size: number) => [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]].map(([x, y]) => [lon + x! * size, lat + y! * size])
  const tower = (i: number, lon: number, h: number) => ({ ...feature(lon, 37.5001, i), h, ring: box(lon, 37.5001, 0.0003) })
  const houses = Array.from({ length: 60 }, (_, i) => ({ ...feature(0, 0, i + 10), h: 6, ring: box(126.963 + (i % 10) * 0.00012, 37.5006 + Math.floor(i / 10) * 0.00012, 0.00008) }))
  // z13 bucket ~ 0.0027 deg: towers 1 and 2 share a bucket, tower 3 is in another one
  const items = componentItems([tower(1, 126.9601, 120), tower(2, 126.9606, 90), tower(3, 126.9801, 100), ...houses]), key = '13/6985/3174'
  expect(bucketOf(items[0]!.f.ring, key)).toBe(bucketOf(items[1]!.f.ring, key))
  expect(bucketOf(items[0]!.f.ring, key)).not.toBe(bucketOf(items[2]!.f.ring, key))
  expect(landmarkOrder(items, key)).toEqual([items[0]!.f.key, items[2]!.f.key])
  const node = generalizeNode(items, key)
  expect(node.landmarks).toBe(2)
  const kept = node.rows.filter(r => r.components === 1 && r.roof - r.ground > 95)
  expect(kept.map(r => Math.round(r.f.z! + r.f.h))).toEqual([252, 232]) // the 120 m and 100 m towers stand as themselves
})

test('over the byte target, the least voluminous features are dropped, still counted, and the measured error follows', () => {
  const rows = Array.from({ length: 400 }, (_, i) => ({ ...feature(127 + (i % 20) * 0.0011, 37.5 + Math.floor(i / 20) * 0.0011, i + 1), h: 3 + (i % 7) * 9 }))
  const items = componentItems(rows), key = '13/6985/3174', free = generalizeNode(items, key), tight = generalizeNode(items, key, undefined, 4000)
  expect(free.mesh.length).toBeGreaterThan(4000)
  expect(free.dropped).toBe(0)
  expect(tight.mesh.length).toBeLessThanOrEqual(4000)
  expect(tight.dropped).toBeGreaterThan(0)
  expect(tight.error).toBeGreaterThan(free.error)
  expect(tight.error).toBeLessThanOrEqual(Math.max(free.error, HLOD_CHILD_ERROR_CAP * tight.eps) + 1e-9) // a drop costs at most 2 x the level eps
  expect(tight.rows.reduce((s, r) => s + r.components, 0)).toBe(400)
  expect(tight.rows.reduce((s, r) => s + r.buildingAnchors, 0)).toBe(400)
  // the most voluminous features are the ones kept
  const volume = (r: { f: { h: number }; area: number }) => r.area * r.f.h
  expect(tight.rows.length).toBeLessThan(free.rows.length)
  expect(Math.max(...tight.rows.map(volume))).toBeGreaterThanOrEqual(Math.max(...free.rows.map(volume))) // plus folded drops
})

test('scattered rural buildings never close into a slab; dense blocks are mostly built and keep their height bands', () => {
  const box = (lon: number, lat: number, size: number) => [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]].map(([x, y]) => [lon + x! * size, lat + y! * size])
  // 300 houses (~9 x 11 m) 60-90 m apart over ~1.5 km, and a dense town of 400 houses 3-4 m apart with 15 towers.
  const rural = Array.from({ length: 300 }, (_, i) => ({ ...feature(0, 0, i + 1), h: 6, ring: box(127 + (i % 20) * 0.0008 + (i % 3) * 0.0002, 37.5 + Math.floor(i / 20) * 0.0007, 0.0001) }))
  const town = Array.from({ length: 400 }, (_, i) => ({ ...feature(0, 0, i + 1001), h: 9, ring: box(127.03 + (i % 20) * 0.00014, 37.5 + Math.floor(i / 20) * 0.00013, 0.0001) }))
  const towers = Array.from({ length: 15 }, (_, i) => ({ ...feature(0, 0, i + 2001), h: 60, ring: box(127.0302 + (i % 5) * 0.0005, 37.5004 + Math.floor(i / 5) * 0.0008, 0.00015) }))
  const items = componentItems([...rural, ...town, ...towers]), node = generalizeNode(items, '13/6985/3174', undefined, 1e9)
  const area = (r: number[][]) => Math.abs(r.reduce((s, p, i) => { const q = r[(i + 1) % r.length]!; return s + p[0]! * q[1]! - q[0]! * p[1]! }, 0)) / 2 * 111320 * 111320 * Math.cos(37.5 * Math.PI / 180)
  expect(node.rows.reduce((s, r) => s + r.components, 0)).toBe(715)
  for (const r of node.rows.filter(r => r.components > 1)) expect(r.area).toBeGreaterThanOrEqual(HLOD_MIN_COVERAGE * (area(r.f.ring) - (r.f.holes ?? []).reduce((s, h) => s + area(h), 0)) * 0.99)
  // no rural block: every feature west of the town stands for at most a handful of houses and is house-sized
  for (const r of node.rows.filter(r => r.f.ring[0]![0]! < 127.025)) { expect(r.components).toBeLessThanOrEqual(3); expect(area(r.f.ring)).toBeLessThan(2000) }
  expect(node.rows.filter(r => r.f.ring[0]![0]! > 127.025 && r.components > 1).length).toBeGreaterThan(0) // the town does merge
  // towers are never averaged with the houses around them
  expect(node.rows.filter(r => r.roof - r.ground >= 60).every(r => r.f.h >= 56)).toBe(true)
})

test('aggregate B3DM counts preserve original GLB and neutral material byte-for-byte', () => {
  const f = feature(127, 37, 1), cells = componentItems([f]), raw = bakeMesh([f], frame(127, 37), false), output = withAggregateCounts(raw, cells)
  const split = (bytes: Uint8Array) => { const h = new DataView(bytes.buffer); const ft = h.getUint32(12, true), bt = h.getUint32(20, true); return { table: decode(bytes.subarray(28 + ft, 28 + ft + bt)), glb: bytes.subarray(28 + ft + bt) } }
  expect(split(output).table.componentCount).toEqual([1])
  expect(split(output).table.buildingAnchorCount).toEqual([1])
  expect(split(output).glb).toEqual(split(raw).glb)
  // Site-hiding columns: bbox per feature, lodBlock = 1 only for a block of several components.
  const b = meshFootprintBounds(f), t = split(output).table
  expect([t.west[0], t.south[0], t.east[0], t.north[0]]).toEqual([127, 37, 127.001, 37.001])
  expect(b[0]).toBeLessThanOrEqual(t.west[0])
  expect(t.lodBlock).toEqual([0])
  // lodBlock follows geometry, not counts: one building with dropped features' counts folded into it stays 0.
  expect(split(withAggregateCounts(raw, [{ ...cells[0]!, components: 7 }])).table.lodBlock).toEqual([0])
  const block = withAggregateCounts(raw, [{ ...cells[0]!, components: 7, block: true }])
  expect(split(block).table.lodBlock).toEqual([1])
})

const square = (lon: number, lat: number, metres: number) => { const dx = metres / (111320 * Math.cos(lat * Math.PI / 180)), dy = metres / 111320
  return [[lon, lat], [lon + dx, lat], [lon + dx, lat + dy], [lon, lat + dy], [lon, lat]] }
const batchTable = (packed: Uint8Array) => { const mesh = gunzipSync(packed), h = new DataView(mesh.buffer, mesh.byteOffset), ft = h.getUint32(12, true)
  return decode(mesh.subarray(28 + ft, 28 + ft + h.getUint32(20, true))) }

test('under the byte target a 70 m tower is kept over small houses (no landmarks in play)', () => {
  // 16 isolated 15 x 15 m houses (9 m, volume 2,025) 300 m apart and one 10 x 10 m 70 m tower (volume 7,000); 17 items: no landmark.
  const houses = Array.from({ length: 16 }, (_, i) => ({ ...feature(0, 0, i + 1), h: 9, ring: square(127 + (i % 4) * 0.0034, 37.5 + Math.floor(i / 4) * 0.0027, 15) }))
  const tower = { ...feature(0, 0, 100), h: 70, ring: square(127.0017, 37.5013, 10) }
  const items = componentItems([...houses, tower]), key = '13/6985/3174', free = generalizeNode(items, key, undefined, 1e9)
  expect(free.landmarks).toBe(0); expect(free.dropped).toBe(0)
  const tight = generalizeNode(items, key, undefined, Math.floor(free.mesh.length * 0.5))
  expect(tight.dropped).toBeGreaterThan(0)
  expect(tight.rows.some(r => r.f.h === 70 && !r.block)).toBe(true) // the tower is kept, low houses are dropped first
  expect(tight.rows.reduce((s, r) => s + r.components, 0)).toBe(17)
})

test('a dropped tower costs its height above the nearest kept roof, uncapped; the kept single building stays lodBlock 0', () => {
  // A: one 450 x 450 m, 9 m building (volume 1.8M) is kept; B: 10 x 10 m, 400 m (volume 40,000) 300 m east of it is dropped.
  const a = { ...feature(0, 0, 1), h: 9, ring: square(127, 37.5, 450) }, b = { ...feature(0, 0, 2), h: 400, ring: square(127.0091, 37.5, 10) }
  const items = componentItems([a, b]), key = '13/6985/3174', free = generalizeNode(items, key, undefined, 1e9)
  expect(free.rows.length).toBe(2)
  const tight = generalizeNode(items, key, undefined, free.mesh.length - 1)
  expect(tight.dropped).toBe(1); expect(tight.rows.length).toBe(1)
  expect(tight.rows[0]!.f.h).toBe(9); expect(tight.rows[0]!.components).toBe(2); expect(tight.rows[0]!.roof).toBe(132 + 400)
  expect(tight.vertical).toBeGreaterThanOrEqual(391 - 1e-6) // 400 m roof above the kept 9 m roof, same ground
  expect(tight.error).toBeGreaterThanOrEqual(391 - 1e-6)
  expect(tight.error).toBeGreaterThan(HLOD_CHILD_ERROR_CAP * tight.eps) // the vertical term is not capped like the 2D one
  expect(tight.horizontal).toBeLessThanOrEqual(Math.max(free.horizontal, HLOD_CHILD_ERROR_CAP * tight.eps) + 1e-9)
  expect(tight.rows[0]!.block).toBe(false)
  expect(batchTable(tight.mesh).lodBlock).toEqual([0]); expect(batchTable(tight.mesh).componentCount).toEqual([2])
})

test('a dropped house on a hill costs its own height, not the slope down to the nearest kept roof', () => {
  const a = { ...feature(0, 0, 1), h: 60, ring: square(127, 37.5, 40) }, b = { ...feature(0, 0, 2), z: 700, h: 10, ring: square(127.0034, 37.5, 10) } // A outranks B
  const items = componentItems([a, b]), key = '13/6985/3174', free = generalizeNode(items, key, undefined, 1e9)
  const tight = generalizeNode(items, key, undefined, free.mesh.length - 1)
  expect(tight.dropped).toBe(1)
  expect(tight.vertical).toBeCloseTo(Math.max(free.vertical, 10), 6) // 710 m roof above its 700 m ground, not 710 - 192
  expect(tight.error).toBeLessThanOrEqual(Math.max(free.error, HLOD_CHILD_ERROR_CAP * tight.eps) + 1e-9)
})

test('every taken block is dense and stands for several members, including blocks re-generalized after sparse rejects', () => {
  // Deterministic mixed scene: dense clusters, their fringes and scattered houses, so passes reject sparse blocks and re-run.
  let seed = 7; const rand = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648
  const rows: Footprint[] = []
  for (let c = 0; c < 6; c++) {
    const cx = 127 + c * 0.004, cy = 37.5 + (c % 2) * 0.004, n = 30 + c * 25, spread = 0.0006 + c * 0.0004
    for (let i = 0; i < n; i++) rows.push({ ...feature(0, 0, rows.length + 1), h: 6 + Math.floor(rand() * 3) * 3, ring: square(cx + (rand() - 0.5) * spread * (1 + (i % 3)), cy + (rand() - 0.5) * spread * (1 + (i % 3)), 8 + rand() * 14) })
  }
  const items = componentItems(rows), node = generalizeNode(items, '13/6985/3174', undefined, 1e9)
  const area = (r: number[][]) => Math.abs(r.reduce((s, p, i) => { const q = r[(i + 1) % r.length]!; return s + p[0]! * q[1]! - q[0]! * p[1]! }, 0)) / 2 * 111320 * 111320 * Math.cos(37.5 * Math.PI / 180)
  expect(node.rows.reduce((s, r) => s + r.components, 0)).toBe(rows.length)
  expect(node.rows.some(r => r.block)).toBe(true)
  for (const r of node.rows) {
    expect(r.block).toBe(r.components > 1) // nothing dropped: geometry and counts agree
    if (r.block) expect(r.area).toBeGreaterThanOrEqual(HLOD_MIN_COVERAGE * (area(r.f.ring) - (r.f.holes ?? []).reduce((s, h) => s + area(h), 0)) * 0.99)
  }
})

test('generalized nodes mark their blocks: lodBlock follows componentCount and every bbox holds its outline', () => {
  const rows = Array.from({ length: 400 }, (_, i) => feature(127 + (i % 20) * 0.0002, 37.5 + Math.floor(i / 20) * 0.0002, i + 1))
  const node = generalizeNode(componentItems(rows), '13/6985/3174'), mesh = gunzipSync(node.mesh)
  const h = new DataView(mesh.buffer, mesh.byteOffset), ft = h.getUint32(12, true), t = decode(mesh.subarray(28 + ft, 28 + ft + h.getUint32(20, true)))
  expect(node.dropped).toBe(0) // nothing folded: lodBlock (geometry) and componentCount agree
  expect(t.lodBlock).toEqual(t.componentCount.map((c: number) => c > 1 ? 1 : 0))
  expect(t.lodBlock.some((v: number) => v === 1)).toBe(true)
  node.rows.forEach((r, i) => { for (const [x, y] of r.f.ring) expect(t.west[i] <= x! && x! <= t.east[i] && t.south[i] <= y! && y! <= t.north[i]).toBe(true) })
})

test('output identity carries the generalizer and mesh baker source hashes', async () => {
  for (const name of ['generalize-buildings.ts', 'prebuilt-mesh.ts'])
    expect(LOD_CODE_SHA256[name]).toBe(createHash('sha256').update(await readFile(join(import.meta.dir, '../features/world/lib', name))).digest('hex'))
})

/** Computed transform of an inline tile: product of every ancestor's transform (column-major). */
const enuAt = (m: number[]) => { const up = [m[8]!, m[9]!, m[10]!]; return frame(Math.atan2(up[1]!, up[0]!) * 180 / Math.PI, Math.asin(up[2]!) * 180 / Math.PI).transform }

test('inline hierarchy: z5-z10 in tileset.json, one JSON per z11 subtree, three JSON hops to a region, composed frames and nested bounds', async () => {
  const features = [feature(127.01, 37.5, 1), feature(127.06, 37.5, 2), feature(129.1, 35.2, 3), feature(126.5, 33.5, 4)]
  const regions: RegionInput[] = features.map((f, i) => ({ owner: `14/${tileXY(f.ring[0]![0]!, f.ring[0]![1]!, 14).join('/')}`, uri: `regions/${i}/tileset.json`, folder: String(i) }))
  const files = new Map<string, Uint8Array>()
  const io: HlodIO = { write: async (p, b) => { if (files.has(p)) throw Error('Overwrite'); files.set(p, b) }, read: async p => files.get(p)!, leaf: async r => {
    const f = features[Number(r.folder)]!; return { features: [f], error: 30, rootError: 12, bounds: meshFootprintBounds(f), low: -12, high: 151 }
  } }
  const result = await buildGlobalHlod(regions, io)
  expect(result.assetPacking).toBe('gzip6-mesh-and-metadata-v1')
  expect(result.components).toBe(4); expect(result.buildings).toBe(4); expect(result.regions).toBe(4)
  const jsons = [...files.keys()].filter(p => p.endsWith('.json')).sort()
  expect(jsons.filter(p => p !== 'tileset.json').every(p => /^nodes\/11-\d+-\d+\.json$/.test(p))).toBe(true)
  expect(jsons.length).toBe(1 + 3) // the two Seoul regions share one z11 node
  const leafURIs: string[] = [], seen = new Set<string>()
  const visit = (node: any, parentWorld: number[], file: string, hops: number, parentSphere?: number[], parentError = Infinity) => {
    const world = node.transform ? multiply(parentWorld, node.transform) : parentWorld
    const center = point(world, node.boundingVolume.sphere.slice(0, 3)), radius = node.boundingVolume.sphere[3]
    if (parentSphere) expect(Math.hypot(...center.map((v, i) => v - parentSphere[i]!)) + radius).toBeLessThanOrEqual(parentSphere[3]! + 1e-6)
    expect(node.geometricError).toBeLessThanOrEqual(parentError)
    if (!node.content) { // z5-z10 carry no content: their error only decides where z11 takes over
      expect(node.refine).toBe('REPLACE'); expect(node.children.length).toBeLessThanOrEqual(4)
      for (const child of node.children) visit(child, world, file, hops, [...center, radius], node.geometricError)
      return
    }
    const uri: string = node.content.uri, folder = file.includes('/') ? 'nodes/' : ''
    if (uri.endsWith('.b3dm.gz')) {
      expect(node.refine).toBe('REPLACE')
      expect(node.children.length).toBeLessThanOrEqual(4)
      enuAt(world).forEach((v, i) => expect(Math.abs(v - world[i]!)).toBeLessThan(i >= 12 ? 1e-3 : 1e-9))
      const path = folder + uri; expect(files.has(path)).toBe(true); seen.add(path)
      const packed = files.get(path)!, mesh = gunzipSync(packed)
      expect(packed).toEqual(new Uint8Array(gzipSync(mesh, { level: 6 })))
      const header = new DataView(mesh.buffer, mesh.byteOffset, mesh.byteLength), ft = header.getUint32(12, true), bt = header.getUint32(20, true)
      const table = decode(mesh.subarray(28 + ft, 28 + ft + bt))
      expect(table.componentCount.reduce((a: number, b: number) => a + b, 0)).toBe(node.extras.components)
      expect(table.buildingAnchorCount.reduce((a: number, b: number) => a + b, 0)).toBe(node.extras.buildings)
      for (const child of node.children) visit(child, world, file, hops, [...center, radius], node.geometricError)
    } else if (uri.endsWith('tileset.json')) {
      world.forEach((v, i) => expect(Math.abs(v - [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1][i]!)).toBeLessThan(1e-6)) // reset to ECEF for the absolute regional root
      expect(hops + 1).toBe(3)
      leafURIs.push(uri)
    } else {
      expect(file).toBe('tileset.json'); world.forEach((v, i) => expect(Math.abs(v - [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1][i]!)).toBeLessThan(1e-6))
      const sub = decode(files.get(uri)!).root
      enuAt(sub.transform).forEach((v, i) => expect(Math.abs(v - sub.transform[i]!)).toBeLessThan(i >= 12 ? 1e-3 : 1e-9))
      visit(sub, world, uri, hops + 1, [...center, radius], node.geometricError)
    }
  }
  const top = decode(files.get('tileset.json')!)
  expect(top.root.content).toBeUndefined() // z5: no content
  expect(top.root.geometricError).toBeGreaterThanOrEqual(nodeWidth(`5/${tileXY(127.01, 37.5, 5).join('/')}`) / HLOD_EMPTY_ERROR_DIVISOR)
  expect([...files.keys()].filter(p => p.endsWith('.b3dm.gz')).every(p => Number(/nodes\/(\d+)-/.exec(p)![1]) >= HLOD_CONTENT_MIN_LEVEL)).toBe(true)
  visit(top.root, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], 'tileset.json', 1)
  expect(leafURIs.sort()).toEqual(regions.map(r => `../${r.uri}`).sort())
  expect(seen).toEqual(new Set([...files.keys()].filter(p => p.endsWith('.b3dm.gz'))))
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
  const sphere = top.root.boundingVolume.sphere, world = point(top.root.transform, sphere.slice(0, 3))
  for (const f of features) for (const p of f.ring) for (const h of [-12, f.z! + f.h]) expect(Math.hypot(...earth(p[0]!, p[1]!, h).map((v, i) => v - world[i]!))).toBeLessThan(sphere[3])
  const repeated = new Map<string, Uint8Array>()
  const repeat = await buildGlobalHlod(regions, { ...io, write: async (p, b) => { repeated.set(p, b) }, read: async p => repeated.get(p)! })
  expect(repeat.files).toEqual(result.files)
  for (const [name, bytes] of repeated) expect(bytes).toEqual(files.get(name)!)
})

test('a regional root error enters z13 clamped to the level scale, so one broken region cannot inflate its ancestors', async () => {
  const f = feature(127, 37.5, 1), owner = `14/${tileXY(127, 37.5, 14).join('/')}`, files = new Map<string, Uint8Array>()
  const leaf = (rootError: number) => async () => ({ features: [f], error: 3634, rootError, bounds: meshFootprintBounds(f), low: -12, high: 151 })
  const build = async (rootError: number) => {
    files.clear()
    await buildGlobalHlod([{ owner, uri: 'r/tileset.json', folder: '' }], { write: async (p, b) => { files.set(p, b) }, read: async p => files.get(p)!, leaf: leaf(rootError) })
    return decode(files.get('tileset.json')!).root
  }
  const outlier = await build(3634), normal = await build(10), cap = HLOD_CHILD_ERROR_CAP * nodeWidth(parentOf(owner)) / HLOD_EPS_DIVISOR
  expect(outlier.children[0].geometricError).toBeCloseTo(cap, 6)
  expect(outlier.geometricError).toBeCloseTo(Math.max(outlier.extras.ownError, cap), 6)
  expect(normal.children[0].geometricError).toBe(10)
  expect(normal.geometricError).toBe(Math.max(normal.extras.ownError, 10))
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

test('regional entry error is the bake top-level half (re-LOD invariant); rootError is the measured root', async () => {
  const f=packedLeafFixture()
  expect((await f.load()).error).toBe(30)
  ;(f.tileset as any).geometricError=60;f.put('tileset.json',f.tileset,false)
  expect((await f.load()).error).toBe(30)
  f.tileset.root.geometricError=4;f.put('tileset.json',f.tileset,false)
  expect((await f.load()).error).toBe(30)
  expect((await f.load()).rootError).toBe(4) // the measured root the HLOD hands over to
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
