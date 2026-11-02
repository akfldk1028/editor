import { expect, test } from 'bun:test'
import { createHash } from 'node:crypto'
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { gunzipSync } from 'node:zlib'
import { encodeCandidatePayload, NGII_ASSET_PACKING, verifyExistingCandidate } from './bake-ngii-region'
import { readRegionalHlodLeaf } from './ngii-global-hlod'
import { bakedLeaves, bindPin, listRegionFolders, main, parseShard, relodName, relodRegion, RELOD_CODE_SHA256, RELOD_ROOT_BYTES_SLACK, useGeneralizedRoot } from './relod-ngii-regions'
import { bakeMesh, frame, meshFootprintBounds, BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import { tileXY, type Footprint } from '../features/world/lib/building-geometry'
import { REGION_LOD_REVISION } from '../features/world/lib/generalize-buildings'

const sha = (b: Uint8Array | string) => createHash('sha256').update(b).digest('hex')
const enc = (v: unknown) => new TextEncoder().encode(JSON.stringify(v))
const PIN = { sourcePlan: 'a'.repeat(64), sourcePlanFileSHA256: 'b'.repeat(64), expectedTerrain: 'c'.repeat(64), inventorySHA256: 'd'.repeat(64),
  mode: 'completed-canonical-database', mesh: BUILDING_MESH_REVISION, assetPacking: NGII_ASSET_PACKING, contract: 'resolved-ancestor-grid-v1' }

/** Mirror of bake-ngii-region's tree for one synthetic region (root -> z15 -> z16, gzip packing). */
async function bakeFixture(root: string, rootError = 300) {
  const [rx, ry] = tileXY(129.05, 35.14, 14), N = 2 ** 14
  const lon = (x: number) => x / N * 360 - 180, lat = (y: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / N))) * 180 / Math.PI
  const w = lon(rx), e = lon(rx + 1), n = lat(ry), s = lat(ry + 1), features: Footprint[] = []
  let id = 0
  for (let i = 0; i < 24; i++) for (let j = 0; j < 24; j++) {
    const x = w + (e - w) * (i + 0.3) / 24, y = s + (n - s) * (j + 0.3) / 24, dx = (e - w) / 24 * 0.9, dy = (n - s) / 24 * 0.9
    features.push({ key: `ngii:${(id++).toString(16).padStart(64, '0')}/0`, pnu: '', s: 'e', h: 4 + (i * j) % 30, z: 10 + j * 0.5,
      ring: [[x, y], [x + dx, y], [x + dx, y + dy], [x, y + dy], [x, y]] })
  }
  const owner = `14/${rx}/${ry}`, folder = join(root, `14-${rx}-${ry}-${'e'.repeat(16)}`)
  await mkdir(folder, { recursive: true })
  const files: any[] = []
  const save = async (name: string, decoded: Uint8Array, zip: boolean) => {
    const p = zip ? encodeCandidatePayload(decoded) : undefined, bytes = p ? p.bytes : decoded
    await writeFile(join(folder, name), bytes); files.push({ path: name, bytes: bytes.length, sha256: sha(bytes), ...p?.metadata })
  }
  const boxes = features.map(meshFootprintBounds)
  const box = boxes.reduce((a, b) => [Math.min(a[0]!, b[0]), Math.min(a[1]!, b[1]), Math.max(a[2]!, b[2]), Math.max(a[3]!, b[3])], [Infinity, Infinity, -Infinity, -Infinity])
  const origin = frame((box[0]! + box[2]!) / 2, (box[1]! + box[3]!) / 2)
  const node = async (z: number, x: number, y: number, rows: Footprint[], children: any[]) => {
    const b = [Infinity, Infinity, -Infinity, -Infinity], hs = [Infinity, -Infinity]
    for (const f of rows) { const r = meshFootprintBounds(f); b[0] = Math.min(b[0]!, r[0]); b[1] = Math.min(b[1]!, r[1]); b[2] = Math.max(b[2]!, r[2]); b[3] = Math.max(b[3]!, r[3]); hs[0] = Math.min(hs[0]!, Math.min(0, f.z!) - 12); hs[1] = Math.max(hs[1]!, f.z! + f.h + 1) }
    const uri = `${z}-${x}-${y}.b3dm.gz`
    await save(uri, bakeMesh(rows, origin, z < 16), true)
    return { boundingVolume: { region: [...b.map(v => v * Math.PI / 180), ...hs] }, geometricError: z === 16 ? 0 : z === 14 ? rootError : Math.min(150, rootError), refine: 'REPLACE', content: { uri }, ...(children.length ? { children } : {}) }
  }
  const leafOf = (f: Footprint) => tileXY(f.ring[0]![0]!, f.ring[0]![1]!, 16).join('/')
  const c15: any[] = []
  for (let dx = 0; dx < 2; dx++) for (let dy = 0; dy < 2; dy++) {
    const x = rx * 2 + dx, y = ry * 2 + dy, group: Footprint[] = [], leaves: any[] = []
    for (let a = 0; a < 2; a++) for (let b = 0; b < 2; b++) {
      const rows = features.filter(f => leafOf(f) === `${x * 2 + a}/${y * 2 + b}`)
      if (rows.length) { group.push(...rows); leaves.push(await node(16, x * 2 + a, y * 2 + b, rows, [])) }
    }
    if (group.length) c15.push(await node(15, x, y, group, leaves))
  }
  const top = await node(14, rx, ry, features, c15)
  await save('tileset.json', enc({ asset: { version: '1.0' }, geometricError: 2 * rootError, root: { ...top, transform: origin.transform } }), false)
  await save('footprints.json.gz', enc(features), true)
  await save('ground-source.json.gz', enc({ buildings: [] }), true)
  const receipt = { schema: 'ngii-region-candidate-v1', completeRegion: true, inputSHA256: 'f'.repeat(64), sourcePlanSHA256: PIN.sourcePlan,
    sourcePlanFileSHA256: PIN.sourcePlanFileSHA256, terrainSHA256: PIN.expectedTerrain, terrainContract: PIN.contract, meshRevision: BUILDING_MESH_REVISION,
    assetPacking: NGII_ASSET_PACKING, inventorySHA256: PIN.inventorySHA256, owner, buildings: features.length, components: features.length,
    supportedGroundBuildings: features.length, unresolvedGroundBuildings: 0, bounds: box, files }
  await writeFile(join(folder, 'candidate-receipt.json'), JSON.stringify(receipt, null, 2))
  await writeFile(join(root, 'candidate-inputs.json'), JSON.stringify(PIN))
  await writeFile(join(root, 'queue-inputs.json'), JSON.stringify({ output: root, regionsSHA256: 'd'.repeat(64) }))
  return { owner, folder, features, receipt }
}

test('shard parsing and region listing', async () => {
  expect(parseShard()).toEqual({ index: 0, count: 1 })
  expect(parseShard('3/8')).toEqual({ index: 3, count: 8 })
  for (const bad of ['8/8', '1', 'a/b']) expect(() => parseShard(bad)).toThrow('Shard')
  const root = await mkdtemp(join(tmpdir(), 'relod-list-'))
  await mkdir(join(root, '14-1-2-' + 'a'.repeat(16))); await mkdir(join(root, '.staging')); await mkdir(join(root, '14-1-2-short'))
  expect(await listRegionFolders(root)).toEqual([{ owner: '14/1/2', folder: join(root, '14-1-2-' + 'a'.repeat(16)) }])
  await mkdir(join(root, '14-1-2-' + 'b'.repeat(16)))
  await expect(listRegionFolders(root)).rejects.toThrow('Duplicate')
  await rm(root, { recursive: true, force: true })
})

test('re-LOD writes a new verified region: generalized root, generalized z15 quadrants over the z16 leaves, carried bytes identical', async () => {
  const src = await mkdtemp(join(tmpdir(), 'relod-src-')), out = await mkdtemp(join(tmpdir(), 'relod-out-'))
  try {
    const f = await bakeFixture(src), before = await readdir(f.folder)
    const r = await relodRegion(f.folder, f.owner, { output: out, checkSpace: async () => {}, rebuildLeaves: true, linkUnchanged: true })
    expect(r.resumed).toBe(false)
    expect(await readdir(f.folder)).toEqual(before) // source untouched
    const receiptRaw = await readFile(join(f.folder, 'candidate-receipt.json'))
    expect(r.folder).toBe(join(out, relodName(f.owner, sha(receiptRaw)).name))
    expect(r.folder.endsWith(f.folder.slice(-16))).toBe(false)
    const receipt = JSON.parse(await readFile(join(r.folder, 'candidate-receipt.json'), 'utf8'))
    expect(receipt.lodRevision).toBe(REGION_LOD_REVISION)
    expect(receipt.lod.rootSource).toBe('generalized')
    for (const k of ['schema', 'owner', 'buildings', 'components', 'meshRevision', 'assetPacking', 'terrainSHA256', 'inputSHA256', 'bounds', 'supportedGroundBuildings'])
      expect(receipt[k]).toEqual((f.receipt as any)[k])
    expect(await verifyExistingCandidate(r.folder, { schema: 'ngii-region-candidate-v1', owner: f.owner, completeRegion: true, meshRevision: BUILDING_MESH_REVISION,
      assetPacking: NGII_ASSET_PACKING, buildings: f.features.length, components: f.features.length })).toBe(true)
    const tileset = JSON.parse(await readFile(join(r.folder, 'tileset.json'), 'utf8')), old = JSON.parse(await readFile(join(f.folder, 'tileset.json'), 'utf8'))
    // Entry = root error (top = 2 x root, like the bake); R0 >= R1 >= leaves.
    expect(tileset.geometricError).toBe(2 * tileset.root.geometricError)
    expect(tileset.root.transform).toEqual(old.root.transform)
    expect(tileset.root.geometricError).toBe(receipt.lod.geometricError)
    expect(tileset.root.geometricError).toBeLessThan(old.root.geometricError)
    const quads = tileset.root.children.filter((c: any) => c.content.uri.startsWith('15-'))
    expect(quads.length).toBeGreaterThan(0)
    expect(quads.length).toBe(receipt.lod.quadrants.filter((q: any) => q.used).length)
    for (const q of quads) {
      expect(q.geometricError).toBeLessThan(tileset.root.geometricError)
      expect(q.children.every((c: any) => c.content.uri.startsWith('16-') && c.geometricError === 0)).toBe(true)
      for (const k of [0, 1, 4]) expect(q.boundingVolume.region[k]).toBeGreaterThanOrEqual(tileset.root.boundingVolume.region[k])
      for (const k of [2, 3, 5]) expect(q.boundingVolume.region[k]).toBeLessThanOrEqual(tileset.root.boundingVolume.region[k])
    }
    expect(tileset.root.children.flatMap((c: any) => c.content.uri.startsWith('15-') ? c.children : [c])).toEqual(bakedLeaves(old))
    const names = await readdir(r.folder)
    expect(names.filter(n => n.startsWith('15-')).sort()).toEqual(quads.map((q: any) => q.content.uri).sort())
    for (const n of names.filter(n => n.startsWith('16-') || n.startsWith('footprints') || n.startsWith('ground')))
      expect(sha(await readFile(join(r.folder, n)))).toBe(sha(await readFile(join(f.folder, n))))
    const region = tileset.root.boundingVolume.region, oldRegion = old.root.boundingVolume.region
    expect(region.every(Number.isFinite)).toBe(true)
    for (const k of [0, 1, 4]) expect(region[k]).toBeLessThanOrEqual(oldRegion[k])
    for (const k of [2, 3, 5]) expect(region[k]).toBeGreaterThanOrEqual(oldRegion[k])
    // R0 and R1 batch tables: bbox per feature for site hiding, lodBlock marking blocks; bbox contains the feature's lon/lat.
    const levels = [{ uri: tileset.root.content.uri, stats: receipt.lod }, ...quads.map((q: any) => ({ uri: q.content.uri, stats: receipt.lod.quadrants.find((x: any) => x.uri === q.content.uri) }))]
    for (const { uri, stats } of levels) {
      const b3dm = gunzipSync(await readFile(join(r.folder, uri)))
      const dv = new DataView(b3dm.buffer, b3dm.byteOffset)
      expect(dv.getUint32(0, true)).toBe(0x6d643362)
      expect(dv.getUint32(8, true)).toBe(b3dm.length)
      const ft = dv.getUint32(12, true), bt = JSON.parse(new TextDecoder().decode(b3dm.subarray(28 + ft, 28 + ft + dv.getUint32(20, true))))
      expect(bt.key.length).toBe(stats.features)
      expect(bt.lodBlock.filter((v: number) => v === 1).length).toBe(stats.blocks)
      bt.key.forEach((k: string, i: number) => {
        expect(bt.lodBlock[i]).toBe(k.startsWith('blk:') ? 1 : 0)
        expect(bt.west[i] <= bt.lon[i] && bt.lon[i] <= bt.east[i] && bt.south[i] <= bt.lat[i] && bt.lat[i] <= bt.north[i]).toBe(true)
      })
      expect((28 + ft + dv.getUint32(20, true)) % 8).toBe(0)
    }
    expect(receipt.lod.quadrants.reduce((s: number, q: any) => s + q.buildings, 0)).toBe(f.features.length)
    // Downstream national HLOD reader accepts it; its entry error is the measured root error.
    const leaf = await readRegionalHlodLeaf(receipt, n => readFile(join(r.folder, n)))
    const oldLeaf = await readRegionalHlodLeaf(f.receipt, n => readFile(join(f.folder, n)))
    expect(leaf.error).toBe(tileset.root.geometricError)
    expect(leaf.error).toBe(receipt.lod.entryGeometricError)
    expect(leaf.features).toEqual(oldLeaf.features)
    // Resume: identical second run is a verified skip.
    expect((await relodRegion(f.folder, f.owner, { output: out, checkSpace: async () => {} })).resumed).toBe(true)
  } finally { await rm(src, { recursive: true, force: true }); await rm(out, { recursive: true, force: true }) }
})

test('CLI pins the output root to the source, re-binds queue inputs, and refuses a changed source leaf', async () => {
  const src = await mkdtemp(join(tmpdir(), 'relod-cli-src-')), out = join(await mkdtemp(join(tmpdir(), 'relod-cli-out-')), 'v4')
  try {
    const f = await bakeFixture(src)
    await main(['--input', src, '--output', out, '--reserve-gib', '1', '--shard', '0/1'])
    const pin = JSON.parse(await readFile(join(out, 'candidate-inputs.json'), 'utf8')), queue = JSON.parse(await readFile(join(out, 'queue-inputs.json'), 'utf8'))
    expect(pin.lodRevision).toBe(REGION_LOD_REVISION); expect(pin.mesh).toBe(BUILDING_MESH_REVISION)
    expect(queue.output).toBe(out); expect(queue.lodSourceOutput).toBe(src); expect(queue.regionsSHA256).toBe('d'.repeat(64))
    expect((await listRegionFolders(out)).map(r => r.owner)).toEqual([f.owner])
    // An empty shard is a no-op.
    await main(['--input', src, '--output', out, '--reserve-gib', '1', '--shard', '1/2'])
    const out2 = join(out, '..', 'v4b'), leaf = (await readdir(f.folder)).find(n => n.startsWith('16-'))!
    const bytes = await readFile(join(f.folder, leaf)); bytes[bytes.length - 1] ^= 1; await writeFile(join(f.folder, leaf), bytes)
    // A failing region is recorded and the shard exits non-zero at the end; a rerun retries (and records) it again.
    for (let run = 0; run < 2; run++) {
      await expect(main(['--input', src, '--output', out2, '--reserve-gib', '1'])).rejects.toThrow('Re-LOD failed for 1 region')
      const rows = (await readFile(join(out2, 'failures-0-of-1.jsonl'), 'utf8')).trim().split('\n').map(l => JSON.parse(l))
      expect(rows).toHaveLength(1); expect(rows[0].owner).toBe(f.owner); expect(rows[0].error).toContain('mismatch')
    }
    expect((await listRegionFolders(out2)).length).toBe(0)
  } finally { await rm(src, { recursive: true, force: true }); await rm(join(out, '..'), { recursive: true, force: true }) }
})

test('when generalizing gains nothing the bake root is carried byte-identical with its own error', async () => {
  const src = await mkdtemp(join(tmpdir(), 'relod-tiny-src-')), out = await mkdtemp(join(tmpdir(), 'relod-tiny-out-'))
  try {
    const f = await bakeFixture(src, 1)
    const r = await relodRegion(f.folder, f.owner, { output: out, checkSpace: async () => {} })
    expect(r.lod!.rootSource).toBe('carried-bake-root')
    const tileset = JSON.parse(await readFile(join(r.folder, 'tileset.json'), 'utf8')), old = JSON.parse(await readFile(join(f.folder, 'tileset.json'), 'utf8'))
    expect(tileset.root.geometricError).toBe(1); expect(tileset.geometricError).toBe(2)
    expect(tileset.root.boundingVolume).toEqual(old.root.boundingVolume)
    expect(sha(await readFile(join(r.folder, tileset.root.content.uri)))).toBe(sha(await readFile(join(f.folder, old.root.content.uri))))
    expect(tileset.root.children).toEqual(bakedLeaves(old))
    const receipt = JSON.parse(await readFile(join(r.folder, 'candidate-receipt.json'), 'utf8'))
    expect(new Set(receipt.files.map((x: any) => x.path)).size).toBe(receipt.files.length)
    expect((await readRegionalHlodLeaf(receipt, n => readFile(join(r.folder, n)))).error).toBe(1)
  } finally { await rm(src, { recursive: true, force: true }); await rm(out, { recursive: true, force: true }) }
})

test('concurrent pin publication is atomic: every writer agrees, no partial file, a mismatch is refused', async () => {
  const root = await mkdtemp(join(tmpdir(), 'relod-pin-'))
  try {
    const path = join(root, 'candidate-inputs.json'), value = { ...PIN, pad: 'x'.repeat(1 << 16) }
    await Promise.all(Array.from({ length: 16 }, () => bindPin(path, value)))
    expect(JSON.parse(await readFile(path, 'utf8'))).toEqual(value)
    expect((await readdir(root)).filter(n => n.endsWith('.part'))).toEqual([])
    await expect(bindPin(path, { ...value, pad: 'y' })).rejects.toThrow('identity mismatch')
    // A half-written pin (older non-atomic writer) is retried until it is complete.
    const half = join(root, 'half.json'), text = JSON.stringify(value)
    await writeFile(half, text.slice(0, 100))
    let waits = 0
    await bindPin(half, value, async () => { if (++waits === 2) await writeFile(half, text) })
    expect(waits).toBe(2)
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('root choice prefers lower error and accepts larger bytes up to the slack', () => {
  expect(RELOD_ROOT_BYTES_SLACK).toBe(1.5)
  expect(useGeneralizedRoot(50, 120_000, 300, 100_000)).toBe(true) // better error, 1.2x bytes
  expect(useGeneralizedRoot(50, 150_000, 300, 100_000)).toBe(true)
  expect(useGeneralizedRoot(50, 150_001, 300, 100_000)).toBe(false)
  expect(useGeneralizedRoot(300, 10_000, 300, 100_000)).toBe(false) // no error gain
})

test('a leaf payload assigned to two quadrants is refused', () => {
  const leaf = (uri: string) => ({ boundingVolume: { region: [] }, geometricError: 0, refine: 'REPLACE', content: { uri } })
  const quad = (uri: string, leaves: any[]) => ({ boundingVolume: { region: [] }, geometricError: 10, refine: 'REPLACE', content: { uri }, children: leaves })
  expect(bakedLeaves({ root: { ...quad('14-0-0.b3dm.gz', [quad('15-0-0.b3dm.gz', [leaf('16-0-0.b3dm.gz')]), quad('15-1-0.b3dm.gz', [leaf('16-2-0.b3dm.gz')])]) } })).toHaveLength(2)
  expect(() => bakedLeaves({ root: { ...quad('14-0-0.b3dm.gz', [quad('15-0-0.b3dm.gz', [leaf('16-0-0.b3dm.gz')]), quad('15-1-0.b3dm.gz', [leaf('16-0-0.b3dm.gz')])]) } }))
    .toThrow('more than one node')
})

test('output name carries this file, the generalizer and the mesh baker source hashes', async () => {
  const lib = join(import.meta.dir, '../features/world/lib')
  expect(RELOD_CODE_SHA256).toEqual({ 'relod-ngii-regions.ts': sha(await readFile(join(import.meta.dir, 'relod-ngii-regions.ts'))),
    'generalize-buildings.ts': sha(await readFile(join(lib, 'generalize-buildings.ts'))), 'prebuilt-mesh.ts': sha(await readFile(join(lib, 'prebuilt-mesh.ts'))) })
})
