import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir, statfs, lstat, readdir, rename } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { gzipSync, gunzipSync } from 'node:zlib'
import { bakeMesh, frame, earth, meshFootprintBounds, BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import type { Footprint } from '../features/world/lib/building-geometry'

export const GLOBAL_HLOD_REVISION = 'ngii-global-occupied-quadtree-v1'
export const HLOD_ASSET_PACKING = 'gzip6-mesh-and-metadata-v1'
type Bounds = [number, number, number, number]
export type Cell = { bounds: Bounds; ground: number; roof: number; components: number; buildingAnchors: number }
export type RegionInput = { owner: string; uri: string; folder: string }
type Descriptor = { key: string; bounds: Bounds; low: number; high: number; sphere: number[]; error: number; components: number; buildings: number; regions: number; uri: string }
type FileReceipt = { path: string; sha256: string; bytes: number; contentEncoding?: 'gzip'; decodedBytes?: number; decodedSHA256?: string }
export type HlodIO = { write: (path: string, bytes: Uint8Array) => Promise<void>; read: (path: string) => Promise<Uint8Array>; leaf: (region: RegionInput) => Promise<{ features: Footprint[]; error: number; bounds: Bounds; low: number; high: number }> }
const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value))
const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex')
const parse = (bytes: Uint8Array) => JSON.parse(new TextDecoder().decode(bytes))
const rad = Math.PI / 180
const id = (key: string) => key.replaceAll('/', '-')
const parent = (key: string) => { const [z, x, y] = key.split('/').map(Number); return `${z! - 1}/${Math.floor(x! / 2)}/${Math.floor(y! / 2)}` }
const union = (a: Bounds, b: Bounds): Bounds => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]
const distance = (a: number[], b: number[]) => Math.hypot(...a.slice(0, 3).map((v, i) => v - b[i]!))
// A convex ECEF sphere also contains triangle interiors/chords below the ellipsoid.
const regionSphere = (b: Bounds, low: number, high: number) => [...earth((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, (low + high) / 2),
  (6378137 + Math.max(Math.abs(low), Math.abs(high))) * ((b[2] - b[0] + b[3] - b[1]) * rad / 2) + (high - low) / 2 + 2]

/** Column-major rigid inverse: external roots already carry their absolute ENU frame. */
export function rigidInverse(m: number[]): number[] {
  if (m.length !== 16 || m.some(v => !Number.isFinite(v)) || m[3] !== 0 || m[7] !== 0 || m[11] !== 0 || m[15] !== 1) throw Error('Invalid rigid transform')
  for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) {
    const dot = [0, 1, 2].reduce((s, i) => s + m[a * 4 + i]! * m[b * 4 + i]!, 0)
    if (Math.abs(dot - Number(a === b)) > 1e-10) throw Error('Transform is not rigid')
  }
  const out = [m[0]!, m[4]!, m[8]!, 0, m[1]!, m[5]!, m[9]!, 0, m[2]!, m[6]!, m[10]!, 0, 0, 0, 0, 1]
  for (let r = 0; r < 3; r++) out[12 + r] = -[0, 1, 2].reduce((s, c) => s + out[c * 4 + r]! * m[12 + c]!, 0)
  return out
}

export function occupiedCells(cells: Cell[], key: string): Cell[] {
  const [z, tx, ty] = key.split('/').map(Number), n = 2 ** z!, result = new Map<string, Cell>()
  for (const cell of cells) {
    const lon = (cell.bounds[0] + cell.bounds[2]) / 2, lat = (cell.bounds[1] + cell.bounds[3]) / 2
    const x = (lon + 180) / 360 * n, y = (1 - Math.asinh(Math.tan(Math.max(-85, Math.min(85, lat)) * rad)) / Math.PI) / 2 * n
    // An owned component can cross its quadtree cell. Keep its full shape bounds.
    const bucket = `${Math.max(0, Math.min(15, Math.floor((x - tx!) * 16)))}/${Math.max(0, Math.min(15, Math.floor((y - ty!) * 16)))}`
    const previous = result.get(bucket)
    result.set(bucket, previous ? { bounds: union(previous.bounds, cell.bounds), ground: Math.min(previous.ground, cell.ground),
      roof: Math.max(previous.roof, cell.roof), components: previous.components + cell.components, buildingAnchors: previous.buildingAnchors + cell.buildingAnchors } : { ...cell })
  }
  return [...result.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, cell]) => cell)
}

export function componentCells(features: Footprint[]): Cell[] {
  const seen = new Set<string>(), buildings = new Map<string, Set<number>>()
  const cells = features.map(f => {
    const match = /^(ngii:[a-f0-9]{64})\/(\d+)$/.exec(f.key)
    if (!match || seen.has(f.key) || !Number.isFinite(f.z) || !Number.isFinite(f.h) || f.h <= 0 || f.ring.length < 4) throw Error('Invalid or duplicate canonical component')
    seen.add(f.key)
    const index = Number(match[2]), parts = buildings.get(match[1]!) ?? new Set<number>(); parts.add(index); buildings.set(match[1]!, parts)
    return { bounds: meshFootprintBounds(f), ground: f.z!, roof: f.z! + f.h, components: 1, buildingAnchors: Number(index === 0) }
  })
  for (const parts of buildings.values()) if (![...parts].sort((a, b) => a - b).every((part, i) => part === i)) throw Error('Missing canonical component')
  return cells
}

/** Preserve the original GLB/material and extend only the B3DM batch-table JSON. */
export function withAggregateCounts(bytes: Uint8Array, cells: Cell[]): Uint8Array {
  const h = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  if (h.getUint32(0, true) !== 0x6d643362 || h.getUint32(16, true) || h.getUint32(24, true)) throw Error('Unexpected B3DM layout')
  const ft = h.getUint32(12, true), oldBT = h.getUint32(20, true), oldEnd = 28 + ft + oldBT
  const table = parse(bytes.subarray(28 + ft, oldEnd))
  if (parse(bytes.subarray(28, 28 + ft)).BATCH_LENGTH !== cells.length) throw Error('Aggregate batch count mismatch')
  const raw = encode({ ...table, componentCount: cells.map(c => c.components), buildingAnchorCount: cells.map(c => c.buildingAnchors),
    sourceMinGround: cells.map(c => c.ground), sourceMaxRoof: cells.map(c => c.roof) })
  const bt = new Uint8Array(Math.ceil(raw.length / 8) * 8).fill(32); bt.set(raw)
  const out = new Uint8Array(28 + ft + bt.length + bytes.length - oldEnd); out.set(bytes.subarray(0, 28 + ft)); out.set(bt, 28 + ft); out.set(bytes.subarray(oldEnd), 28 + ft + bt.length)
  const header = new DataView(out.buffer); header.setUint32(8, out.length, true); header.setUint32(20, bt.length, true)
  return out
}

export async function buildGlobalHlod(regions: RegionInput[], io: HlodIO) {
  if (!regions.length || new Set(regions.map(r => r.owner)).size !== regions.length) throw Error('Empty or duplicate regions')
  for (const r of regions) if (!/^14\/\d+\/\d+$/.test(r.owner) || r.owner.split('/').slice(1).some(v => Number(v) >= 2 ** 14)
    || !r.uri || r.uri.includes('\\') || (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(r.uri) && !/^https?:/.test(r.uri))) throw Error('Invalid regional reference')
  const totals = { buildings: 0, components: 0, regions: regions.length }, files: FileReceipt[] = []
  const write = async (path: string, decoded: Uint8Array, compressed = false) => {
    const bytes = compressed ? new Uint8Array(gzipSync(decoded, { level: 6 })) : decoded
    const sha256 = digest(bytes), decodedSHA256 = digest(decoded)
    await io.write(path, bytes)
    const stored = await io.read(path)
    if (stored.length !== bytes.length || digest(stored) !== sha256) throw Error('HLOD readback mismatch')
    if (compressed) {
      const unpacked = gunzipSync(stored)
      if (unpacked.length !== decoded.length || digest(unpacked) !== decodedSHA256) throw Error('HLOD decoded readback mismatch')
    }
    files.push({ path, sha256, bytes: bytes.length, ...(compressed ? { contentEncoding: 'gzip' as const, decodedBytes: decoded.length, decodedSHA256 } : {}) })
  }
  let level = new Map<string, Descriptor>(), inputs = new Map(regions.map(r => [r.owner, r]))
  for (let z = 13; z >= 0; z--) {
    const groups = new Map<string, string[]>()
    for (const key of z === 13 ? inputs.keys() : level.keys()) { const p = parent(key), rows = groups.get(p) ?? []; rows.push(key); groups.set(p, rows) }
    const next = new Map<string, Descriptor>()
    for (const [key, childKeys] of [...groups].sort(([a], [b]) => a.localeCompare(b))) {
      const cells: Cell[] = [], children: Descriptor[] = []
      for (const childKey of childKeys.sort()) {
        if (z === 13) {
          const region = inputs.get(childKey)!, source = await io.leaf(region), rows = componentCells(source.features)
          if (!rows.length) throw Error('Empty regional leaf')
          const buildings = rows.reduce((s, r) => s + r.buildingAnchors, 0)
          children.push({ key: childKey, uri: /^(https?:|\/)/.test(region.uri) ? region.uri : `../${region.uri}`, bounds: source.bounds,
            low: source.low, high: source.high, sphere: regionSphere(source.bounds, source.low, source.high), error: source.error, buildings, components: rows.length, regions: 1 })
          for (const row of rows) cells.push(row)
          totals.buildings += buildings; totals.components += rows.length
        } else {
          children.push(level.get(childKey)!); cells.push(...parse(await io.read(`summaries/${id(childKey)}.json`)))
        }
      }
      const coarse = occupiedCells(cells, key), bounds = children.map(c => c.bounds).reduce(union)
      const fullBounds = coarse.map(c => c.bounds).reduce(union, bounds)
      const low = Math.min(...children.map(c => c.low), ...coarse.map(c => Math.min(0, c.ground) - 12)) - 1
      const high = Math.max(...children.map(c => c.high), ...coarse.map(c => c.roof)) + 1
      const error = Math.max(...coarse.map(c => Math.hypot((c.bounds[2] - c.bounds[0]) * 112000, (c.bounds[3] - c.bounds[1]) * 112000) + c.roof - c.ground), ...children.map(c => c.error * 2), 1)
      const origin = frame((fullBounds[0] + fullBounds[2]) / 2, (fullBounds[1] + fullBounds[3]) / 2)
      const center = origin.transform.slice(12, 15)
      let radius = Math.max(...children.map(c => distance(center, c.sphere) + c.sphere[3]!))
      for (const cell of coarse) for (const lon of [cell.bounds[0], cell.bounds[2]]) for (const lat of [cell.bounds[1], cell.bounds[3]]) {
        for (const height of [Math.min(0, cell.ground) - 12, cell.roof]) radius = Math.max(radius, distance(center, earth(lon, lat, height)) + 2)
      }
      const features: Footprint[] = coarse.map((c, i) => ({ key: `${key}:${i}`, pnu: '', s: 'u', z: c.ground, h: c.roof - c.ground,
        ring: [[c.bounds[0], c.bounds[1]], [c.bounds[2], c.bounds[1]], [c.bounds[2], c.bounds[3]], [c.bounds[0], c.bounds[3]], [c.bounds[0], c.bounds[1]]] }))
      await write(`nodes/${id(key)}.b3dm.gz`, withAggregateCounts(bakeMesh(features, origin, false), coarse), true)
      await write(`summaries/${id(key)}.json`, encode(coarse))
      const descriptor: Descriptor = { key, bounds: fullBounds, low, high, sphere: [...center, radius], error, buildings: children.reduce((s, c) => s + c.buildings, 0),
        components: children.reduce((s, c) => s + c.components, 0), regions: children.reduce((s, c) => s + c.regions, 0), uri: `${id(key)}.json` }
      if (coarse.reduce((s, c) => s + c.components, 0) !== descriptor.components || coarse.reduce((s, c) => s + c.buildingAnchors, 0) !== descriptor.buildings) throw Error('HLOD coverage loss')
      await write(`nodes/${id(key)}.json`, encode({ asset: { version: '1.0', tilesetVersion: GLOBAL_HLOD_REVISION }, geometricError: error * 2,
        root: { boundingVolume: { sphere: [0, 0, 0, radius] }, transform: origin.transform, geometricError: error, refine: 'REPLACE', content: { uri: `${id(key)}.b3dm.gz` },
          extras: { buildings: descriptor.buildings, components: descriptor.components, regions: descriptor.regions, occupiedCells: coarse.length },
          children: children.map(c => ({ boundingVolume: { sphere: c.sphere }, geometricError: c.error,
            refine: 'REPLACE', transform: rigidInverse(origin.transform), content: { uri: c.uri } })) } }))
      next.set(key, descriptor)
    }
    level = next
    if (level.size === 1) break
  }
  const root = [...level.values()][0]!
  await write('tileset.json', encode({ asset: { version: '1.0', tilesetVersion: GLOBAL_HLOD_REVISION }, geometricError: root.error * 2,
    root: { boundingVolume: { sphere: root.sphere }, geometricError: root.error, refine: 'REPLACE', content: { uri: `nodes/${root.uri}` } } }))
  return { schema: GLOBAL_HLOD_REVISION, assetPacking: HLOD_ASSET_PACKING, ...totals, root: root.key, files, activated: false }
}

export async function readRegionalHlodLeaf(receipt: any, read: (name: string) => Promise<Uint8Array>) {
  if (receipt.assetPacking !== HLOD_ASSET_PACKING) throw Error('Regional packing identity mismatch')
  const load = async (name: string) => {
    const rows = receipt.files.filter((f: FileReceipt) => f.path === name)
    if (rows.length !== 1) throw Error('Regional payload receipt missing or duplicated')
    const row = rows[0] as FileReceipt, bytes = await read(name)
    if (row.bytes !== bytes.length || row.sha256 !== digest(bytes)) throw Error('Regional payload changed')
    let decoded = bytes
    if (name.endsWith('.gz')) {
      if (row.contentEncoding !== 'gzip' || !Number.isSafeInteger(row.decodedBytes) || row.decodedBytes! <= 0
        || !/^[a-f0-9]{64}$/.test(row.decodedSHA256 ?? '')) throw Error('Invalid regional gzip receipt')
      decoded = gunzipSync(bytes)
      if (decoded.length !== row.decodedBytes || digest(decoded) !== row.decodedSHA256) throw Error('Regional decoded payload changed')
    } else if (row.contentEncoding !== undefined) throw Error('Unexpected regional metadata encoding')
    return parse(decoded)
  }
  const features = await load('footprints.json.gz') as Footprint[], tileset = await load('tileset.json'), volume = tileset.root.boundingVolume.region
  if (!Array.isArray(features) || features.length !== receipt.components || componentCells(features).reduce((s, c) => s + c.buildingAnchors, 0) !== receipt.buildings || !Array.isArray(volume) || volume.length !== 6 || !volume.every(Number.isFinite)) throw Error('Regional coverage mismatch')
  if (!Array.isArray(receipt.bounds) || receipt.bounds.length !== 4 || !receipt.bounds.every(Number.isFinite)) throw Error('Invalid regional bounds')
  const expectedFrame = frame((receipt.bounds[0] + receipt.bounds[2]) / 2, (receipt.bounds[1] + receipt.bounds[3]) / 2).transform
  rigidInverse(tileset.root.transform)
  if (expectedFrame.some((v, i) => Math.abs(v - tileset.root.transform[i]) > 1e-6)) throw Error('Regional root must use its absolute ENU frame')
  for (const cell of componentCells(features)) if (cell.bounds[0] * rad < volume[0] - 1e-10 || cell.bounds[1] * rad < volume[1] - 1e-10
    || cell.bounds[2] * rad > volume[2] + 1e-10 || cell.bounds[3] * rad > volume[3] + 1e-10 || Math.min(0, cell.ground) - 12 < volume[4] || cell.roof > volume[5]) throw Error('Regional bounds omit full component geometry')
  return { features, error: tileset.root.geometricError, bounds: volume.slice(0, 4).map((v: number) => v / rad) as Bounds, low: volume[4], high: volume[5] }
}

/** A single HLOD writer owns this identity-pinned directory; interrupted .part bytes are never published. */
export async function openHlodOutput(output: string, identity: unknown, space: () => Promise<void>) {
  await space()
  await mkdir(output, { recursive: true })
  if ((await lstat(output)).isSymbolicLink()) throw Error('Invalid HLOD output directory')
  const pin = encode(identity), pinName = 'candidate-inputs.json'
  const matches = async (path: string, bytes: Uint8Array) => {
    try {
      const stamp = await lstat(path)
      if (!stamp.isFile() || stamp.isSymbolicLink() || stamp.size !== bytes.length || digest(await readFile(path)) !== digest(bytes)) throw Error('HLOD existing output mismatch')
      return true
    } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false; throw error }
  }
  const write = async (name: string, bytes: Uint8Array) => {
    if (!/^(?:nodes\/|summaries\/)?[a-zA-Z0-9.-]+$/.test(name) || name.includes('..') || name.endsWith('.part')) throw Error('Invalid HLOD output path')
    const path = join(output, name), part = path + '.part'
    if (name.includes('/')) {
      const directory = join(output, name.split('/')[0]!)
      await mkdir(directory, { recursive: true })
      if ((await lstat(directory)).isSymbolicLink()) throw Error('Invalid HLOD output directory')
    }
    if (await matches(path, bytes)) return
    await space()
    try {
      const stamp = await lstat(part)
      if (!stamp.isFile() || stamp.isSymbolicLink()) throw Error('Invalid HLOD partial file')
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error }
    await writeFile(part, bytes)
    await matches(part, bytes)
    for (let attempt = 0; ; attempt++) {
      if (await matches(path, bytes)) return
      try { await rename(part, path); break }
      catch (error) {
        if (attempt >= 4 || !['EPERM', 'EACCES', 'EBUSY'].includes((error as NodeJS.ErrnoException).code ?? '')) throw error
        await new Promise(resolve => setTimeout(resolve, 25 * 2 ** attempt))
      }
    }
  }
  if (!await matches(join(output, pinName), pin)) {
    if ((await readdir(output)).some(name => name !== pinName + '.part')) throw Error('Unbound HLOD output directory')
    await write(pinName, pin)
  }
  return { write, read: (name: string) => readFile(join(output, name)) }
}

export async function main(args = process.argv.slice(2)) {
  const option = (key: string) => { const i = args.indexOf(key); if (i < 0 || !args[i + 1]) throw Error(`Missing ${key}`); return args[i + 1]! }
  const input = JSON.parse(await readFile(resolve(option('--input')), 'utf8')) as { regions: RegionInput[]; sourcePlanSHA256: string; terrainSHA256: string }
  if (![input.sourcePlanSHA256, input.terrainSHA256].every(s => /^[a-f0-9]{64}$/.test(s))) throw Error('Missing source/terrain pin')
  const receipts = new Map<string, any>(), pins: { owner: string; receiptSHA256: string; uri: string }[] = []
  for (const r of [...input.regions].sort((a, b) => a.owner.localeCompare(b.owner))) {
    const raw = await readFile(join(r.folder, 'candidate-receipt.json')), receipt = JSON.parse(raw.toString())
    if (receipt.owner !== r.owner || receipt.sourcePlanSHA256 !== input.sourcePlanSHA256 || receipt.terrainSHA256 !== input.terrainSHA256 || receipt.meshRevision !== BUILDING_MESH_REVISION || receipt.assetPacking !== HLOD_ASSET_PACKING) throw Error('Regional source identity mismatch')
    receipts.set(r.owner, receipt); pins.push({ owner: r.owner, receiptSHA256: digest(raw), uri: r.uri })
  }
  const identity = { revision: GLOBAL_HLOD_REVISION, assetPacking: HLOD_ASSET_PACKING, mesh: BUILDING_MESH_REVISION, sourcePlanSHA256: input.sourcePlanSHA256, terrainSHA256: input.terrainSHA256,
    implementationSHA256: digest(await readFile(import.meta.path)), pins,
    sampleOnly: [...receipts.values()].some(r => r.completeRegion !== true), completeRegion: [...receipts.values()].every(r => r.completeRegion === true), publishable: false }
  const dataRoot = resolve(option('--data-root')), output = join(dataRoot, 'world-buildings', 'national', digest(encode(identity)))
  const space = async () => { const s = await statfs(dataRoot); if (s.bavail * s.bsize < 20 * 1024 ** 3) throw Error('HLOD needs_storage: 20GiB reserve') }
  const storage = await openHlodOutput(output, identity, space)
  const io: HlodIO = { ...storage, leaf: region => readRegionalHlodLeaf(receipts.get(region.owner), name => readFile(join(region.folder, name))) }

  const result = await buildGlobalHlod(input.regions, io)
  await storage.write('candidate-receipt.json', new TextEncoder().encode(JSON.stringify({ ...result, ...identity }, null, 2)))
  console.log(JSON.stringify({ output, ...result, files: result.files.length }))
}
if (import.meta.main) await main()
