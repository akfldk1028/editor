import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { readFile, writeFile, mkdir, statfs, lstat, readdir, rename } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { gzipSync, gunzipSync } from 'node:zlib'
import { bakeMesh, frame, earth, meshFootprintBounds, coarseFootprint, BUILDING_MESH_REVISION } from '../features/world/lib/prebuilt-mesh'
import { generalizeBuildings } from '../features/world/lib/generalize-buildings'
import { footprintBounds, type Footprint } from '../features/world/lib/building-geometry'

// Pinned by infra/data/prepare_ngii_national_release.py (HLOD); output identity also carries implementationSHA256.
export const GLOBAL_HLOD_REVISION = 'ngii-global-generalized-quadtree-v2'
export const HLOD_ASSET_PACKING = 'gzip6-mesh-and-metadata-v1'
type Bounds = [number, number, number, number]
/**
 * Content levels z11-z13 only. Per content node: its children's content (z13: the regions' real component footprints;
 * above: the child nodes' output features) is generalized with generalizeBuildings, coarse to fine: eps starts at node
 * width / 32 and halves down to node width / 256 (z13 ~ 15 m, z12 ~ 30 m, z11 ~ 60 m). A merged block is kept only
 * where it is mostly built: its members' real footprint area >= HLOD_MIN_COVERAGE of the block's area; the members of
 * a sparser block are tried again at the next finer eps, and what is still sparse at the finest eps stays as its own
 * footprint (no closing across fields and valleys). Each pass groups by real height band (towers are never averaged
 * with houses) and by a 64 eps spatial cell (bounded error raster). The generalizer works at eps 16 on a 2 m error
 * raster, so it runs on coordinates and heights scaled by eps / 16: its raster is then eps / 8, and every measured
 * length scales back exactly. Landmarks: at most one per 16x16 bucket of the node tile, tall (>= 28 m) and in the
 * node's top 5% by h * sqrt(area), kept as themselves. Byte target per node mesh: HLOD_TARGET_GZ (gzip); over it,
 * the least voluminous features (area x height; landmarks and towers are not exempt) are dropped and
 * their counts folded into the nearest kept feature; each drop costs its 2D distance to the kept coverage (capped) and,
 * uncapped, how far its roof rises above the nearest kept feature's roof (at most its own height).
 */
export const HLOD_GRID = 16, HLOD_EPS_DIVISOR = 32, HLOD_MIN_EPS_DIVISOR = 256, HLOD_MIN_COVERAGE = 0.2, HLOD_TARGET_GZ = 150_000, HLOD_LANDMARK_HEIGHT = 28, HLOD_LANDMARK_SHARE = 0.05
/** Nodes at this level are separate JSON files holding their subtree (z11-z13) inline; above it everything is inline in tileset.json. */
export const HLOD_FILE_LEVEL = 11
/** Nodes above this level carry no content (buildings are a few pixels at most there); their error, max(children,
 * node width / HLOD_EMPTY_ERROR_DIVISOR), only decides where z11 content appears. */
export const HLOD_CONTENT_MIN_LEVEL = 11, HLOD_EMPTY_ERROR_DIVISOR = 16
/** A feature and what it stands for: counts, the source extremes for the batch table, and its members' real footprint area (m2).
 * `block`: the geometry merges more than one source component (lodBlock); counts folded in for the byte target do not change it. */
export type Item = { f: Footprint; components: number; buildingAnchors: number; ground: number; roof: number; area: number; block: boolean }
export type RegionInput = { owner: string; uri: string; folder: string }
type Link = { uri: string; sphere: number[]; error: number }
type Descriptor = { key: string; z: number; transform: number[]; sphere: number[]; radius: number; bounds: Bounds; error: number; ownError: number; horizontal: number; vertical: number; attempts: number
  components: number; buildings: number; regions: number; features: number; landmarks: number; dropped: number; eps: number; gz: number; content: boolean; children: string[]; links: Link[] }
type FileReceipt = { path: string; sha256: string; bytes: number; contentEncoding?: 'gzip'; decodedBytes?: number; decodedSHA256?: string }
export type Leaf = { features: Footprint[]; error: number; rootError?: number; bounds: Bounds; low: number; high: number }
export type HlodIO = { write: (path: string, bytes: Uint8Array) => Promise<void>; read: (path: string) => Promise<Uint8Array>; leaf: (region: RegionInput) => Promise<Leaf> }
const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value))
const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex')
const parse = (bytes: Uint8Array) => JSON.parse(new TextDecoder().decode(bytes))
const rad = Math.PI / 180
/** Source hashes of the code that decides output bytes besides the caller's own file: the generalizer and the mesh
 * baker. Part of the HLOD and re-LOD output identities, so an edit there without a revision bump cannot reuse old outputs. */
export const LOD_CODE_SHA256 = Object.fromEntries(['generalize-buildings.ts', 'prebuilt-mesh.ts']
  .map(name => [name, digest(readFileSync(join(import.meta.dir, '../features/world/lib', name)))])) as Record<string, string>
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
/** Column-major a x b. An inline child carries inverse(parent ENU) x child ENU, so its computed transform is its own ENU. */
export const multiply = (a: number[], b: number[]) => Array.from({ length: 16 }, (_, i) => [0, 1, 2, 3].reduce((s, k) => s + a[k * 4 + i % 4]! * b[Math.floor(i / 4) * 4 + k]!, 0))

const metres = 111320
/** Ground width of a web-mercator tile at its centre latitude. */
export function nodeWidth(key: string) {
  const [z, , y] = key.split('/').map(Number), n = 2 ** z!, lat = Math.atan(Math.sinh(Math.PI * (1 - 2 * (y! + 0.5) / n)))
  return 40075016.686 / n * Math.cos(lat)
}
export function bucketOf(ring: number[][], key: string) {
  const [z, tx, ty] = key.split('/').map(Number), n = 2 ** z!
  const lon = ring.reduce((s, q) => s + q[0]!, 0) / ring.length, lat = ring.reduce((s, q) => s + q[1]!, 0) / ring.length
  const x = (lon + 180) / 360 * n, y = (1 - Math.asinh(Math.tan(Math.max(-85, Math.min(85, lat)) * rad)) / Math.PI) / 2 * n
  return `${Math.max(0, Math.min(HLOD_GRID - 1, Math.floor((x - tx!) * HLOD_GRID)))}/${Math.max(0, Math.min(HLOD_GRID - 1, Math.floor((y - ty!) * HLOD_GRID)))}`
}
const areaOf = (ring: number[][]) => {
  const [ox, oy] = ring[0]!, k = Math.cos(oy! * rad) * metres * metres
  return Math.abs(ring.reduce((s, p, i) => { const q = ring[(i + 1) % ring.length]!; return s + (p[0]! - ox!) * (q[1]! - oy!) - (q[0]! - ox!) * (p[1]! - oy!) }, 0)) / 2 * k
}
const footprintArea = (f: Footprint) => Math.max(0, areaOf(f.ring) - (f.holes ?? []).reduce((s, h) => s + areaOf(h), 0))
// The generalizer's height bands in real metres: <7, 7-14, 14-28, 28-56, >= 56 m.
const heightBand = (h: number) => Math.max(0, Math.min(4, Math.floor(Math.log2(Math.max(h, 1) / 3.5) + 1e-9)))
const centroid = (ring: number[][]) => [ring.reduce((s, q) => s + q[0]!, 0) / ring.length, ring.reduce((s, q) => s + q[1]!, 0) / ring.length]
/** Spatially balanced landmarks: tall, in the node's top share by h * sqrt(area), at most one per bucket, most prominent first. */
export function landmarkOrder(items: Item[], key: string): string[] {
  const score = items.map(r => r.f.h * Math.sqrt(areaOf(r.f.ring)))
  const cut = [...score].sort((a, b) => b - a)[Math.floor(items.length * HLOD_LANDMARK_SHARE)] ?? Infinity
  const order = items.map((_, i) => i).filter(i => items[i]!.f.h >= HLOD_LANDMARK_HEIGHT && score[i]! > cut)
    .sort((a, b) => score[b]! - score[a]! || (items[a]!.f.key < items[b]!.f.key ? -1 : 1))
  const taken = new Set<string>(), keys: string[] = []
  for (const i of order) { const b = bucketOf(items[i]!.f.ring, key); if (!taken.has(b)) { taken.add(b); keys.push(items[i]!.f.key) } }
  return keys
}

/** Every input is represented exactly once (or, dropped for the byte target, counted in its nearest kept feature); the
 * output carries the summed counts, source extremes and real footprint area of its members. */
export function generalizeNode(items: Item[], key: string, childBounds?: Bounds, target = HLOD_TARGET_GZ) {
  const [lon0, lat0] = [0, 1].map(k => items.reduce((s, r) => s + r.f.ring[0]![k]!, 0) / items.length) as [number, number]
  const kx = Math.cos(lat0 * rad) * metres, byKey = new Map(items.map(r => [r.f.key, r]))
  if (byKey.size !== items.length) throw Error('Duplicate HLOD input key')
  const marks = new Set(landmarkOrder(items, key)), width = nodeWidth(key), start = width / HLOD_EPS_DIVISOR, finest = width / HLOD_MIN_EPS_DIVISOR
  let attempts = 0, horizontal = 0, vertical = 0, error = 0
  /** One generalizer pass over `group` at `eps` (no landmarks): features in degrees, members as items, measured errors in metres. */
  const run = (group: Item[], eps: number) => {
    attempts++
    const s = eps / 16, to = (q: number[]) => [(q[0]! - lon0) * kx / (s * metres), (q[1]! - lat0) / s]
    const back = (q: number[]) => [lon0 + q[0]! * s * metres / kx, lat0 + q[1]! * s]
    const scaled = group.map(({ f }) => ({ ...f, ring: f.ring.map(to), ...(f.holes ? { holes: f.holes.map(h => h.map(to)) } : {}), z: f.z! / s, h: f.h / s }))
    const out = generalizeBuildings(scaled, { lon0: 0, lat0: 0, kx: metres }, 16, new Set())
    return { blocks: out.features.map((g, i) => ({ f: { ...g, z: g.z! * s, h: g.h * s, ring: g.ring.map(back), ...(g.holes ? { holes: g.holes.map(h => h.map(back)) } : {}) },
      members: out.members[i]!.map(k => byKey.get(k)!) })), horizontal: out.stats.hausdorffM * s, vertical: out.stats.verticalMaxM * s, error: out.stats.geometricError * s }
  }
  const measure = (r: { horizontal: number; vertical: number; error: number }) => { horizontal = Math.max(horizontal, r.horizontal); vertical = Math.max(vertical, r.vertical); error = Math.max(error, r.error) }
  const edge = (x: number, y: number, a: number[], b: number[]) => {
    const dx = b[0]! - a[0]!, dy = b[1]! - a[1]!, L = dx * dx + dy * dy, t = L ? Math.max(0, Math.min(1, ((x - a[0]!) * dx + (y - a[1]!) * dy) / L)) : 0
    return Math.hypot(x - a[0]! - t * dx, y - a[1]! - t * dy)
  }
  // A single item stands as itself, as its oriented box when that is within 25% of its footprint's area (fewer vertices,
  // the budget's unit); the box's distance from the footprint (corners and edge midpoints) enters the measured error.
  type Kept = { f: Footprint; members: Item[]; block: boolean }
  const local = (q: number[]) => [(q[0]! - lon0) * kx, (q[1]! - lat0) * metres]
  const asItself = (r: Item): Kept => {
    if (r.f.holes?.length || r.f.ring.length <= 5) return { f: r.f, members: [r], block: r.block }
    const box = coarseFootprint(r.f), area = areaOf(box.ring)
    if (!(area <= 1.25 * footprintArea(r.f))) return { f: r.f, members: [r], block: r.block }
    const ring = r.f.ring.map(local), corners = box.ring.slice(0, 4).map(local)
    let deviation = 0
    for (const [k, a] of corners.entries()) for (const q of [a, a.map((v, i) => (v + corners[(k + 1) % 4]![i]!) / 2)])
      deviation = Math.max(deviation, Math.min(...ring.map((p, i) => edge(q[0]!, q[1]!, p, ring[(i + 1) % ring.length]!))))
    horizontal = Math.max(horizontal, deviation); error = Math.max(error, deviation)
    return { f: { ...r.f, ring: box.ring }, members: [r], block: r.block }
  }
  const isDense = (b: { f: Footprint; members: Item[] }) => b.members.length > 1 && b.members.reduce((s, r) => s + r.area, 0) >= HLOD_MIN_COVERAGE * footprintArea(b.f)
  // Kept features: landmarks and passed-through items as themselves, blocks where mostly built.
  const kept: Kept[] = items.filter(r => marks.has(r.f.key)).map(asItself)
  let pending = items.filter(r => !marks.has(r.f.key))
  for (let eps = start; pending.length && eps >= finest * (1 - 1e-9); eps /= 2) {
    const groups = new Map<string, Item[]>(), cell = 64 * eps, next: Item[] = []
    for (const r of pending) {
      // A footprint wider than the cell would stretch its group's error raster far past cell size (memory): as itself.
      const b = footprintBounds(r.f)
      if (Math.max((b[2] - b[0]) * kx, (b[3] - b[1]) * metres) > cell) { kept.push(asItself(r)); continue }
      const [x, y] = centroid(r.f.ring), k = `${heightBand(r.f.h)}:${Math.floor((x! - lon0) * kx / cell)}:${Math.floor((y! - lat0) * metres / cell)}`
      const g = groups.get(k); g ? g.push(r) : groups.set(k, [r])
    }
    for (const [, group] of [...groups].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) {
      if (group.length === 1) { next.push(group[0]!); continue }
      const pass = run(group, eps), dense: Item[] = []
      for (const b of pass.blocks) isDense(b) ? dense.push(...b.members) : next.push(...b.members)
      if (!dense.length) continue
      // Generalize the dense members again alone (the rejected sparse ones are not part of the output) and re-check the
      // result the same way: a block that is now sparse or single goes to the next eps too. The pass's measured error
      // still includes such a re-rejected block (conservative; requiring a clean pass left Busan cores unmerged).
      const final = dense.length === group.length ? pass : run(dense, eps)
      measure(final)
      for (const b of final.blocks) isDense(b) ? kept.push({ f: b.f, members: b.members, block: true }) : next.push(...b.members)
    }
    pending = next
  }
  for (const r of pending) kept.push(asItself(r)) // still sparse at the finest eps: as itself
  // Byte target, keep order: by volume (a 70 m slab outranks small houses). Landmark-first or tower-first orders were
  // measured on the Busan core: up to 171 landmarks (and more h >= 28 m features) alone fill a node's budget and every
  // low-rise block is dropped. The tail is dropped and counted in the kept feature nearest to it. A dropped feature costs its 2D distance to the kept coverage (centroid
  // distance + its own radius, capped at HLOD_CHILD_ERROR_CAP x start eps) and, uncapped, how far its source roofs rise
  // above the nearest kept feature's roof, each at most its own height (a house on a hill above a valley block is missing
  // by its height, not by the slope), so a node that drops buildings (a tower above all) refines early.
  const volume = (k: Kept) => k.members.reduce((s, r) => s + r.area, 0) * k.f.h
  const order = kept.map((k, i) => ({ k, i, v: volume(k) })).sort((a, b) => b.v - a.v || a.i - b.i).map(a => a.k)
  const keptRoof = order.map(k => k.f.z! + k.f.h)
  const rise = (j: number, roof: number) => order[j]!.members.reduce((v, r) => Math.max(v, r.roof - Math.max(r.ground, roof)), 0)
  const shapes = order.map(k => {
    const rings = [k.f.ring, ...(k.f.holes ?? [])].map(r => r.map(local)), xs = rings[0]!.map(q => q[0]!), ys = rings[0]!.map(q => q[1]!)
    const c = centroid(rings[0]!)
    return { rings, box: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)], c, radius: Math.max(...rings[0]!.map(q => Math.hypot(q[0]! - c[0]!, q[1]! - c[1]!))) }
  })
  const inside = (rings: number[][][], x: number, y: number) => {
    let odd = false
    for (const r of rings) for (let k = 0, n = r.length; k < n; k++) {
      const a = r[k]!, b = r[(k + 1) % n]!
      if ((a[1]! > y) !== (b[1]! > y) && x < a[0]! + (y - a[1]!) / (b[1]! - a[1]!) * (b[0]! - a[0]!)) odd = !odd
    }
    return odd
  }
  /** Nearest of the first n kept features to the point, and the distance to its coverage (0 inside). */
  const nearest = (n: number, x: number, y: number) => {
    let best = 0, bd = Infinity
    for (let j = 0; j < n; j++) {
      const b = shapes[j]!.box, lower = Math.hypot(Math.max(0, b[0]! - x, x - b[2]!), Math.max(0, b[1]! - y, y - b[3]!))
      if (lower >= bd) continue
      let d = Infinity
      if (inside(shapes[j]!.rings, x, y)) d = 0
      else for (const r of shapes[j]!.rings) for (let k = 0; k < r.length; k++) d = Math.min(d, edge(x, y, r[k]!, r[(k + 1) % r.length]!))
      if (d < bd) { bd = d; best = j }
    }
    return { best, distance: bd }
  }
  let bounds = childBounds
  for (const k of order) for (const ring of [k.f.ring, ...(k.f.holes ?? [])]) for (const q of ring) bounds = bounds ? union(bounds, [q[0]!, q[1]!, q[0]!, q[1]!]) : [q[0]!, q[1]!, q[0]!, q[1]!]
  const origin = frame((bounds![0] + bounds![2]) / 2, (bounds![1] + bounds![3]) / 2)
  const dropCap = HLOD_CHILD_ERROR_CAP * start
  const bake = (n: number, fold: boolean) => {
    const chosen = order.slice(0, n), groups = chosen.map(k => [...k.members])
    let dropH = 0, dropV = 0
    if (fold) for (let j = n; j < order.length; j++) {
      const s = shapes[j]!, near = nearest(n, s.c[0]!, s.c[1]!)
      groups[near.best]!.push(...order[j]!.members)
      dropH = Math.max(dropH, Math.min(near.distance + s.radius, dropCap)); dropV = Math.max(dropV, rise(j, keptRoof[near.best]!))
    }
    const rows: Item[] = chosen.map((k, i) => {
      const m = groups[i]!
      return { f: { key: `${id(key)}:${i}`, pnu: '', s: k.f.s, z: k.f.z, h: k.f.h, ring: k.f.ring, ...(k.f.holes ? { holes: k.f.holes } : {}) },
        components: m.reduce((a, r) => a + r.components, 0), buildingAnchors: m.reduce((a, r) => a + r.buildingAnchors, 0),
        ground: Math.min(...m.map(r => r.ground)), roof: Math.max(...m.map(r => r.roof)), area: m.reduce((a, r) => a + r.area, 0), block: k.block }
    })
    const mesh = new Uint8Array(gzipSync(withAggregateCounts(bakeMesh(rows.map(r => r.f), origin, false), rows), { level: 6 }))
    return { rows, groups, mesh, dropH, dropV, dropError: Math.max(dropH, dropV), dropped: order.length - n }
  }
  let n = order.length, best = bake(n, true)
  if (best.mesh.length > target && n > 1) {
    let lo = 1, hi = order.length // largest n whose mesh fits (at least one feature is always kept); counts barely change the bytes
    while (hi - lo > Math.max(1, lo >> 6)) { const mid = (lo + hi) >> 1; if (bake(mid, false).mesh.length <= target) lo = mid; else hi = mid }
    for (n = lo, best = bake(n, true); best.mesh.length > target && n > 1;) best = bake(n = Math.max(1, Math.floor(n * 0.98)), true)
  }
  const seen = new Set<Item>()
  for (const m of best.groups) for (const r of m) { if (seen.has(r)) throw Error('HLOD coverage loss'); seen.add(r) }
  if (seen.size !== items.length) throw Error('HLOD coverage loss')
  horizontal = Math.max(horizontal, best.dropH); vertical = Math.max(vertical, best.dropV)
  return { rows: best.rows, eps: start, finest, landmarks: marks.size, dropped: best.dropped, horizontal, vertical, error: Math.max(error, best.dropError),
    bounds: bounds!, origin, mesh: best.mesh, attempts }
}

export function componentItems(features: Footprint[]): Item[] {
  const seen = new Set<string>(), buildings = new Map<string, Set<number>>()
  const items = features.map(f => {
    const match = /^(ngii:[a-f0-9]{64})\/(\d+)$/.exec(f.key)
    if (!match || seen.has(f.key) || !Number.isFinite(f.z) || !Number.isFinite(f.h) || f.h <= 0 || f.ring.length < 4) throw Error('Invalid or duplicate canonical component')
    seen.add(f.key)
    const index = Number(match[2]), parts = buildings.get(match[1]!) ?? new Set<number>(); parts.add(index); buildings.set(match[1]!, parts)
    return { f, components: 1, buildingAnchors: Number(index === 0), ground: f.z!, roof: f.z! + f.h, area: footprintArea(f), block: false }
  })
  for (const parts of buildings.values()) if (![...parts].sort((a, b) => a - b).every((part, i) => part === i)) throw Error('Missing canonical component')
  return items
}

/** Preserve the original GLB/material and extend only the B3DM batch-table JSON. Site-hiding columns as the re-LOD root:
 * each feature's footprint bbox in degrees and lodBlock (1 = geometry merged from several components, 0 = one
 * component's footprint, even when dropped features' counts are folded into it). */
export function withAggregateCounts(bytes: Uint8Array, cells: { f: Footprint; components: number; buildingAnchors: number; ground: number; roof: number; block: boolean }[]): Uint8Array {
  const h = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  if (h.getUint32(0, true) !== 0x6d643362 || h.getUint32(16, true) || h.getUint32(24, true)) throw Error('Unexpected B3DM layout')
  const ft = h.getUint32(12, true), oldBT = h.getUint32(20, true), oldEnd = 28 + ft + oldBT
  const table = parse(bytes.subarray(28 + ft, oldEnd))
  if (parse(bytes.subarray(28, 28 + ft)).BATCH_LENGTH !== cells.length) throw Error('Aggregate batch count mismatch')
  const boxes = cells.map(c => footprintBounds(c.f))
  const raw = encode({ ...table, componentCount: cells.map(c => c.components), buildingAnchorCount: cells.map(c => c.buildingAnchors),
    sourceMinGround: cells.map(c => c.ground), sourceMaxRoof: cells.map(c => c.roof),
    west: boxes.map(b => b[0]), south: boxes.map(b => b[1]), east: boxes.map(b => b[2]), north: boxes.map(b => b[3]), lodBlock: cells.map(c => c.block ? 1 : 0) })
  const bt = new Uint8Array(Math.ceil(raw.length / 8) * 8).fill(32); bt.set(raw)
  const out = new Uint8Array(28 + ft + bt.length + bytes.length - oldEnd); out.set(bytes.subarray(0, 28 + ft)); out.set(bt, 28 + ft); out.set(bytes.subarray(oldEnd), 28 + ft + bt.length)
  const header = new DataView(out.buffer); header.setUint32(8, out.length, true); header.setUint32(20, bt.length, true)
  return out
}

/** Regional root error enters at most at this multiple of the z13 eps: z13 is measured against the real footprints,
 * so the child value only orders refinement; one broken regional root must not inflate every ancestor. */
export const HLOD_CHILD_ERROR_CAP = 2

export async function buildGlobalHlod(regions: RegionInput[], io: HlodIO) {
  if (!regions.length || new Set(regions.map(r => r.owner)).size !== regions.length) throw Error('Empty or duplicate regions')
  for (const r of regions) if (!/^14\/\d+\/\d+$/.test(r.owner) || r.owner.split('/').slice(1).some(v => Number(v) >= 2 ** 14)
    || !r.uri || r.uri.includes('\\') || (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(r.uri) && !/^https?:/.test(r.uri))) throw Error('Invalid regional reference')
  const totals = { buildings: 0, components: 0, regions: regions.length }, files: FileReceipt[] = []
  const write = async (path: string, decoded: Uint8Array, compressed = false, packed?: Uint8Array) => {
    const bytes = packed ?? (compressed ? new Uint8Array(gzipSync(decoded, { level: 6 })) : decoded)
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
  const nodes = new Map<string, Descriptor>(), asset = { version: '1.0', tilesetVersion: GLOBAL_HLOD_REVISION }
  // inline subtree; `base` is the folder of the JSON being written ('' = output root, 'nodes/' = a z11 file)
  const tile = (n: Descriptor, frameOf: number[] | null, base: '' | 'nodes/'): any => {
    const out: any = { boundingVolume: { sphere: [0, 0, 0, n.radius] }, geometricError: n.error, refine: 'REPLACE',
      transform: frameOf ? multiply(rigidInverse(frameOf), n.transform) : n.transform, ...(n.content ? { content: { uri: `${base ? '' : 'nodes/'}${id(n.key)}.b3dm.gz` } } : {}),
      extras: { buildings: n.buildings, components: n.components, regions: n.regions, features: n.features, landmarks: n.landmarks, dropped: n.dropped, eps: n.eps, ownError: n.ownError, horizontal: n.horizontal, vertical: n.vertical } }
    const reset = rigidInverse(n.transform)
    out.children = n.links.length
      ? n.links.map(l => ({ boundingVolume: { sphere: l.sphere }, geometricError: l.error, refine: 'REPLACE', transform: reset, content: { uri: /^(https?:|\/)/.test(l.uri) ? l.uri : `${base ? '../' : ''}${l.uri}` } }))
      : n.children.map(k => nodes.get(k)!).map(c => c.z === HLOD_FILE_LEVEL
        ? { boundingVolume: { sphere: c.sphere }, geometricError: c.error, refine: 'REPLACE', transform: reset, content: { uri: `${base ? '' : 'nodes/'}${id(c.key)}.json` } }
        : tile(c, n.transform, base))
    return out
  }
  let level = new Map<string, string[]>()
  for (const r of regions) { const p = parent(r.owner), rows = level.get(p) ?? []; rows.push(r.owner); level.set(p, rows) }
  const inputs = new Map(regions.map(r => [r.owner, r]))
  for (let z = 13; z >= 0; z--) {
    const done: string[] = []
    for (const [key, childKeys] of [...level].sort(([a], [b]) => a.localeCompare(b))) {
      const items: Item[] = [], links: Link[] = [], children = z === 13 ? [] : childKeys.sort()
      let bounds: Bounds | undefined, childError = 0
      const radiusChildren: number[][] = []
      if (z === 13) {
        const cap = HLOD_CHILD_ERROR_CAP * nodeWidth(key) / HLOD_EPS_DIVISOR
        for (const owner of childKeys.sort()) {
          const region = inputs.get(owner)!, source = await io.leaf(region), rows = componentItems(source.features)
          if (!rows.length) throw Error('Empty regional leaf')
          const error = Math.min(source.rootError ?? source.error, cap), sphere = regionSphere(source.bounds, source.low, source.high)
          links.push({ uri: region.uri, sphere, error }); childError = Math.max(childError, error); radiusChildren.push(sphere)
          bounds = bounds ? union(bounds, source.bounds) : source.bounds
          items.push(...rows)
          totals.buildings += rows.reduce((s, r) => s + r.buildingAnchors, 0); totals.components += rows.length
        }
      } else for (const childKey of children) {
        const c = nodes.get(childKey)!
        childError = Math.max(childError, c.error); radiusChildren.push(c.sphere); bounds = bounds ? union(bounds, c.bounds) : c.bounds
        if (z >= HLOD_CONTENT_MIN_LEVEL) items.push(...parse(gunzipSync(await io.read(`summaries/${id(childKey)}.json.gz`))) as Item[])
      }
      const regionCount = z === 13 ? childKeys.length : children.reduce((s, k) => s + nodes.get(k)!.regions, 0)
      if (z < HLOD_CONTENT_MIN_LEVEL) {
        // No content: nothing is drawn until z11 takes over; the error only decides where that happens.
        const origin = frame((bounds![0] + bounds![2]) / 2, (bounds![1] + bounds![3]) / 2), center = origin.transform.slice(12, 15)
        const radius = Math.max(...radiusChildren.map(s => distance(center, s) + s[3]!)), error = Math.max(childError, nodeWidth(key) / HLOD_EMPTY_ERROR_DIVISOR)
        const sum = (k: 'components' | 'buildings') => children.reduce((s, c) => s + nodes.get(c)![k], 0)
        nodes.set(key, { key, z, transform: origin.transform, sphere: [...center, radius], radius, bounds: bounds!, error, ownError: 0, horizontal: 0, vertical: 0, attempts: 0,
          components: sum('components'), buildings: sum('buildings'), regions: regionCount, features: 0, landmarks: 0, dropped: 0, eps: 0, gz: 0, content: false, children, links })
        done.push(key)
        continue
      }
      const node = generalizeNode(items, key, bounds), origin = node.origin, center = origin.transform.slice(12, 15)
      let radius = Math.max(...radiusChildren.map(s => distance(center, s) + s[3]!))
      for (const r of node.rows) for (const q of r.f.ring) for (const height of [Math.min(0, r.f.z!) - 12, r.f.z! + r.f.h]) radius = Math.max(radius, distance(center, earth(q[0]!, q[1]!, height)) + 2)
      const mesh = node.mesh
      // z13 is measured against the real footprints; above, own error is measured against the children's content.
      const error = z === 13 ? Math.max(node.error, childError) : childError + node.error
      const components = items.reduce((s, r) => s + r.components, 0), buildings = items.reduce((s, r) => s + r.buildingAnchors, 0)
      if (node.rows.reduce((s, r) => s + r.components, 0) !== components || node.rows.reduce((s, r) => s + r.buildingAnchors, 0) !== buildings) throw Error('HLOD coverage loss')
      await write(`nodes/${id(key)}.b3dm.gz`, gunzipSync(mesh), true, mesh)
      if (z > HLOD_CONTENT_MIN_LEVEL) await write(`summaries/${id(key)}.json.gz`, encode(node.rows), true)
      const descriptor: Descriptor = { key, z, transform: origin.transform, sphere: [...center, radius], radius, bounds: node.bounds, error, ownError: node.error, horizontal: node.horizontal, vertical: node.vertical, attempts: node.attempts,
        components, buildings, regions: regionCount,
        features: node.rows.length, landmarks: node.landmarks, dropped: node.dropped, eps: node.eps, gz: mesh.length, content: true, children, links }
      nodes.set(key, descriptor); done.push(key)
      if (z === HLOD_FILE_LEVEL) await write(`nodes/${id(key)}.json`, encode({ asset, geometricError: error * 2, root: tile(descriptor, null, 'nodes/') }))
    }
    if (done.length === 1) break
    const next = new Map<string, string[]>()
    for (const key of done) { const p = parent(key), rows = next.get(p) ?? []; rows.push(key); next.set(p, rows) }
    level = next
  }
  const root = [...nodes.values()].reduce((a, b) => b.z < a.z ? b : a)
  await write('tileset.json', encode({ asset, geometricError: root.error * 2, root: tile(root, null, '') }))
  const levels: Record<number, { nodes: number; gz: number; maxGz: number; features: number; dropped: number; maxError: number; maxOwnError: number }> = {}
  for (const n of nodes.values()) {
    const l = levels[n.z] ??= { nodes: 0, gz: 0, maxGz: 0, features: 0, dropped: 0, maxError: 0, maxOwnError: 0 }
    l.nodes++; l.gz += n.gz; l.maxGz = Math.max(l.maxGz, n.gz); l.features += n.features; l.dropped += n.dropped; l.maxError = Math.max(l.maxError, n.error); l.maxOwnError = Math.max(l.maxOwnError, n.ownError)
  }
  return { schema: GLOBAL_HLOD_REVISION, assetPacking: HLOD_ASSET_PACKING, ...totals, root: root.key, levels, files, activated: false }
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
  const items = Array.isArray(features) ? componentItems(features) : []
  if (!Array.isArray(features) || features.length !== receipt.components || items.reduce((s, c) => s + c.buildingAnchors, 0) !== receipt.buildings || !Array.isArray(volume) || volume.length !== 6 || !volume.every(Number.isFinite)) throw Error('Regional coverage mismatch')
  if (!Array.isArray(receipt.bounds) || receipt.bounds.length !== 4 || !receipt.bounds.every(Number.isFinite)) throw Error('Invalid regional bounds')
  const expectedFrame = frame((receipt.bounds[0] + receipt.bounds[2]) / 2, (receipt.bounds[1] + receipt.bounds[3]) / 2).transform
  rigidInverse(tileset.root.transform)
  if (expectedFrame.some((v, i) => Math.abs(v - tileset.root.transform[i]) > 1e-6)) throw Error('Regional root must use its absolute ENU frame')
  for (const { f } of items) {
    const b = meshFootprintBounds(f)
    if (b[0] * rad < volume[0] - 1e-10 || b[1] * rad < volume[1] - 1e-10 || b[2] * rad > volume[2] + 1e-10 || b[3] * rad > volume[3] + 1e-10
      || Math.min(0, f.z!) - 12 < volume[4] || f.z! + f.h > volume[5]) throw Error('Regional bounds omit full component geometry')
  }
  // Entry error: the bake writes top = 2 x root. A re-LOD region keeps that top but its root carries the smaller
  // measured error of its generalized content; `error` stays the bake's entry (re-LOD invariant), `rootError` is
  // the measured root the HLOD hands over to.
  const entry = Number.isFinite(tileset.geometricError) ? Math.max(tileset.root.geometricError, tileset.geometricError / 2) : tileset.root.geometricError
  return { features, error: entry, rootError: tileset.root.geometricError as number, bounds: volume.slice(0, 4).map((v: number) => v / rad) as Bounds, low: volume[4], high: volume[5] }
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
        // Defender/indexer can hold a fresh file for seconds; an unattended national run must not die on that.
        if (attempt >= 10 || !['EPERM', 'EACCES', 'EBUSY'].includes((error as NodeJS.ErrnoException).code ?? '')) throw error
        await new Promise(resolve => setTimeout(resolve, Math.min(2000, 50 * 2 ** attempt)))
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
    implementationSHA256: digest(await readFile(import.meta.path)), lodCodeSHA256: LOD_CODE_SHA256, pins,
    sampleOnly: [...receipts.values()].some(r => r.completeRegion !== true), completeRegion: [...receipts.values()].every(r => r.completeRegion === true), publishable: false }
  const dataRoot = resolve(option('--data-root')), output = join(dataRoot, 'world-buildings', 'national', digest(encode(identity)))
  const reserve = args.includes('--reserve-gib') ? Number(option('--reserve-gib')) : 20
  if (!(reserve >= 1)) throw Error('Invalid --reserve-gib')
  const space = async () => { const s = await statfs(dataRoot); if (s.bavail * s.bsize < reserve * 1024 ** 3) throw Error(`HLOD needs_storage: ${reserve}GiB reserve`) }
  const storage = await openHlodOutput(output, identity, space)
  const io: HlodIO = { ...storage, leaf: region => readRegionalHlodLeaf(receipts.get(region.owner), name => readFile(join(region.folder, name))) }

  const result = await buildGlobalHlod(input.regions, io)
  await storage.write('candidate-receipt.json', new TextEncoder().encode(JSON.stringify({ ...result, ...identity }, null, 2)))
  console.log(JSON.stringify({ output, ...result, files: result.files.length }))
}
if (import.meta.main) await main()
