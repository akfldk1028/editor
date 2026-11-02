import { coarseFootprint } from './prebuilt-mesh'
import type { Footprint } from './building-geometry'

/**
 * Region generalization for the national 3D buildings (coarse content of a z14 region and its z15 quadrants).
 *
 * Landmarks are the buildings a merge would misrepresent beyond the level's error budget E = eps: a building
 * standing more than eps/2 above its block's roof (plus up to eps/2 of outline movement) stays as itself, at most
 * LANDMARKS_PER_BIN per (8 eps)^2 bin, highest excess first (a dense core cannot crowd out the rest). A landmark is
 * drawn as its oriented box when the box is close to the footprint and its horizontal deviation fits the error the
 * rest of the level already has, otherwise as its footprint. Everything else is grouped by height band x 8 m ground
 * bin and merged into blocks by morphological closing on a raster of cell = eps/2 (Kada 2010-style aggregation),
 * outlined, simplified, and extruded at the members' area-weighted mean roof, based at the members' minimum ground.
 * Every input footprint is represented exactly once: as a landmark, or as a member of one block.
 *
 * The geometric error is measured, not assumed, on a 2 m grid over the original and generalized surfaces (holes
 * respected, each cell's roof = the highest building covering it): max(horizontal Hausdorff distance between the
 * two coverages, max over cells of a vertical bound). A cell covered by both sides counts the roof difference. A cell
 * covered by one side only counts an upper bound of its 3D distance to the other scene (terrain + buildings): its
 * roof point is within min(height above its ground, distance to the other coverage's nearest cell + roof difference
 * there) of it, and the other side's ground point there is within min(height, distance to where the present side
 * ends). So filled gaps, lost buildings and blocks covering lower buildings of other bands are all seen, while a
 * block edge next to a tower is no longer charged the tower's full height.
 *
 * Part of immutable output identity: change REGION_LOD_REVISION whenever the output can change.
 */
export const REGION_LOD_REVISION = 'budget-landmarks-r0eps64-r1eps16-quadrants-v3'
/** z15 quadrant content (R1). */
export const REGION_LOD_EPS_METRES = 16
/** z14 region root content (R0). */
export const REGION_ROOT_EPS_METRES = 64
const GROUND_BIN_METRES = 8
const LANDMARKS_PER_BIN = 32

const M = 111320
export type Projection = { lon0: number; lat0: number; kx: number }
export const localProjection = (lon0: number, lat0: number): Projection => ({ lon0, lat0, kx: Math.cos(lat0 * Math.PI / 180) * M })
const toXY = (p: Projection, q: number[]) => [(q[0]! - p.lon0) * p.kx, (q[1]! - p.lat0) * M]
const toLL = (p: Projection, x: number, y: number) => [p.lon0 + x / p.kx, p.lat0 + y / M]

const ringArea = (r: number[][]) => {
  let s = 0
  for (let i = 0; i < r.length; i++) { const a = r[i]!, b = r[(i + 1) % r.length]!; s += a[0]! * b[1]! - b[0]! * a[1]! }
  return s / 2
}

type Grid = { x0: number; y0: number; cell: number; W: number; H: number }
const gridOver = (rings: number[][][], cell: number, pad: number): Grid => {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const r of rings) for (const q of r) { minX = Math.min(minX, q[0]!); minY = Math.min(minY, q[1]!); maxX = Math.max(maxX, q[0]!); maxY = Math.max(maxY, q[1]!) }
  return { x0: minX - pad, y0: minY - pad, cell, W: Math.ceil((maxX - minX + 2 * pad) / cell) + 1, H: Math.ceil((maxY - minY + 2 * pad) / cell) + 1 }
}
const cellOf = (g: Grid, x: number, y: number) =>
  Math.min(g.H - 1, Math.max(0, Math.floor((y - g.y0) / g.cell))) * g.W + Math.min(g.W - 1, Math.max(0, Math.floor((x - g.x0) / g.cell)))

/** Cells whose centre lies inside the rings (even-odd). */
function rasterRings(g: Grid, rings: number[][][], out: (i: number) => void) {
  let minY = Infinity, maxY = -Infinity
  for (const r of rings) for (const q of r) { minY = Math.min(minY, q[1]!); maxY = Math.max(maxY, q[1]!) }
  const j0 = Math.max(0, Math.ceil((minY - g.y0) / g.cell - 0.5)), j1 = Math.min(g.H - 1, Math.floor((maxY - g.y0) / g.cell - 0.5))
  for (let j = j0; j <= j1; j++) {
    const y = g.y0 + (j + 0.5) * g.cell, xs: number[] = []
    for (const r of rings) for (let k = 0; k < r.length; k++) {
      const a = r[k]!, b = r[(k + 1) % r.length]!
      if ((a[1]! > y) !== (b[1]! > y)) xs.push(a[0]! + (y - a[1]!) / (b[1]! - a[1]!) * (b[0]! - a[0]!))
    }
    xs.sort((a, b) => a - b)
    for (let k = 0; k + 1 < xs.length; k += 2) {
      const i0 = Math.max(0, Math.ceil((xs[k]! - g.x0) / g.cell - 0.5)), i1 = Math.min(g.W - 1, Math.floor((xs[k + 1]! - g.x0) / g.cell - 0.5))
      for (let i = i0; i <= i1; i++) out(j * g.W + i)
    }
  }
}

/** 4-connected supercover of a segment (Amanatides-Woo): one axis step at a time. */
function supercover(g: Grid, a: number[], b: number[], out: (i: number) => void) {
  const x = (a[0]! - g.x0) / g.cell, y = (a[1]! - g.y0) / g.cell, x1 = (b[0]! - g.x0) / g.cell, y1 = (b[1]! - g.y0) / g.cell
  let i = Math.floor(x), j = Math.floor(y)
  const ie = Math.floor(x1), je = Math.floor(y1), dx = x1 - x, dy = y1 - y, sx = Math.sign(dx), sy = Math.sign(dy)
  const tdx = dx ? Math.abs(1 / dx) : Infinity, tdy = dy ? Math.abs(1 / dy) : Infinity
  let tmx = dx > 0 ? (i + 1 - x) * tdx : dx < 0 ? (x - i) * tdx : Infinity
  let tmy = dy > 0 ? (j + 1 - y) * tdy : dy < 0 ? (y - j) * tdy : Infinity
  const mark = () => out(Math.min(g.H - 1, Math.max(0, j)) * g.W + Math.min(g.W - 1, Math.max(0, i)))
  mark()
  for (let n = Math.abs(ie - i) + Math.abs(je - j); n > 0; n--) {
    if (tmx < tmy) { tmx += tdx; i += sx } else { tmy += tdy; j += sy }
    mark()
  }
}

/** Separable square (Chebyshev) structuring element of radius r cells. */
function morph(m: Uint8Array, g: Grid, r: number, dilate: boolean) {
  const tmp = new Uint8Array(m.length), out = new Uint8Array(m.length)
  for (let j = 0; j < g.H; j++) for (let i = 0; i < g.W; i++) {
    let v = dilate ? 0 : 1
    for (let d = -r; d <= r; d++) { const ii = i + d, s = ii < 0 || ii >= g.W ? 0 : m[j * g.W + ii]!; v = dilate ? v | s : v & s }
    tmp[j * g.W + i] = v
  }
  for (let j = 0; j < g.H; j++) for (let i = 0; i < g.W; i++) {
    let v = dilate ? 0 : 1
    for (let d = -r; d <= r; d++) { const jj = j + d, s = jj < 0 || jj >= g.H ? 0 : tmp[jj * g.W + i]!; v = dilate ? v | s : v & s }
    out[j * g.W + i] = v
  }
  return out
}

/** 4-connected labels: with left turns at saddles, each component then has exactly one outer boundary. */
function label4(m: Uint8Array, g: Grid) {
  const lab = new Int32Array(m.length).fill(-1), comps: number[][] = []
  for (let s = 0; s < m.length; s++) {
    if (!m[s] || lab[s]! >= 0) continue
    const id = comps.length, cells = [s]; lab[s] = id
    for (let k = 0; k < cells.length; k++) {
      const c = cells[k]!, i = c % g.W, j = (c - i) / g.W
      for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
        const ii = i + di, jj = j + dj
        if (ii < 0 || jj < 0 || ii >= g.W || jj >= g.H) continue
        const n = jj * g.W + ii
        if (m[n] && lab[n]! < 0) { lab[n] = id; cells.push(n) }
      }
    }
    comps.push(cells)
  }
  return { lab, comps }
}

/** Cell-edge boundary loops of one component, interior on the left (CCW outer, CW holes). */
function traceLoops(cells: number[], lab: Int32Array, id: number, g: Grid): number[][][] {
  const W1 = g.W + 1, out = new Map<number, number[]>()
  const inC = (i: number, j: number) => i >= 0 && j >= 0 && i < g.W && j < g.H && lab[j * g.W + i] === id
  const add = (vx: number, vy: number, dir: number) => { const k = vy * W1 + vx, a = out.get(k); a ? a.push(dir) : out.set(k, [dir]) }
  for (const c of cells) { // dir 0=E, 1=N, 2=W, 3=S
    const i = c % g.W, j = (c - i) / g.W
    if (!inC(i, j - 1)) add(i, j, 0)
    if (!inC(i + 1, j)) add(i + 1, j, 1)
    if (!inC(i, j + 1)) add(i + 1, j + 1, 2)
    if (!inC(i - 1, j)) add(i, j + 1, 3)
  }
  const DX = [1, 0, -1, 0], DY = [0, 1, 0, -1], loops: number[][][] = []
  for (const [start, dirs] of out) {
    while (dirs.length) {
      let k = start, dir = dirs.pop()!
      const loop: number[][] = []
      for (;;) {
        const vx = k % W1, vy = (k - vx) / W1
        loop.push([vx, vy])
        k = (vy + DY[dir]!) * W1 + vx + DX[dir]!
        if (k === start) break
        const cand = out.get(k)!
        let idx = cand.indexOf((dir + 1) % 4); if (idx < 0) idx = cand.indexOf(dir); if (idx < 0) idx = 0
        dir = cand.splice(idx, 1)[0]!
        if (loop.length > 4 * cells.length + 8) throw Error('Block outline trace did not close')
      }
      loops.push(loop)
    }
  }
  return loops
}

function douglasPeucker(pts: number[][], tol: number): number[][] {
  if (pts.length < 3) return pts
  const keep = new Uint8Array(pts.length); keep[0] = keep[pts.length - 1] = 1
  const stack = [[0, pts.length - 1]]
  while (stack.length) {
    const [a, b] = stack.pop()!, A = pts[a!]!, B = pts[b!]!
    const dx = B[0]! - A[0]!, dy = B[1]! - A[1]!, L = Math.hypot(dx, dy) || 1e-9
    let best = -1, bi = -1
    for (let i = a! + 1; i < b!; i++) { const d = Math.abs((pts[i]![0]! - A[0]!) * dy - (pts[i]![1]! - A[1]!) * dx) / L; if (d > best) { best = d; bi = i } }
    if (best > tol) { keep[bi] = 1; stack.push([a!, bi], [bi, b!]) }
  }
  return pts.filter((_, i) => keep[i])
}
function simplifyClosed(loop: number[][], tol: number) {
  let far = 0, fd = -1
  for (let i = 0; i < loop.length; i++) { const d = Math.hypot(loop[i]![0]! - loop[0]![0]!, loop[i]![1]! - loop[0]![1]!); if (d > fd) { fd = d; far = i } }
  const a = douglasPeucker(loop.slice(0, far + 1), tol), b = douglasPeucker([...loop.slice(far), loop[0]!], tol)
  return [...a, ...b.slice(1, -1)]
}

// Height bands: <7, 7-14, 14-28, 28-56, >=56 m; fixed 8 m ground bins keep slopes from merging across terraces.
const band = (h: number) => Math.max(0, Math.min(4, Math.floor(Math.log2(Math.max(h, 1) / 3.5) + 1e-9)))
const groupOf = (f: Footprint) => `${band(f.h)}:${Math.floor(f.z! / GROUND_BIN_METRES)}`

type Prepared = { xy: number[][][]; area: number[]; g: Grid; cell: number }
function prepare(all: Footprint[], p: Projection, eps: number): Prepared {
  const cell = eps / 2, xy = all.map(f => f.ring.map(q => toXY(p, q)))
  return { xy, area: xy.map(r => Math.abs(ringArea(r))), g: gridOver(xy, cell, 3 * cell), cell }
}
type Block = { group: string; mem: number[]; top: number; zmin: number; loops?: number[][][] }
/** Blocks of the given footprints (indices) per height band x ground bin; deterministic order (group, raster component). */
function mergeBlocks(all: Footprint[], { xy, area, g, cell }: Prepared, rows: number[], outline: boolean): Block[] {
  const groups = new Map<string, number[]>(), out: Block[] = []
  for (const i of rows) { const k = groupOf(all[i]!), a = groups.get(k); a ? a.push(i) : groups.set(k, [i]) }
  for (const [group, idx] of [...groups].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)) {
    const m = new Uint8Array(g.W * g.H), set = (c: number) => { m[c] = 1 }
    for (const i of idx) { // filled interior + 4-connected outline: each footprint's cells are 4-connected
      const r = xy[i]!
      rasterRings(g, [r], set)
      for (let k = 0; k < r.length; k++) supercover(g, r[k]!, r[(k + 1) % r.length]!, set)
    }
    const closed = morph(morph(m, g, 1, true), g, 1, false)
    for (let c = 0; c < m.length; c++) closed[c] = closed[c]! | m[c]!
    const { lab, comps } = label4(closed, g), byComp = new Map<number, number[]>()
    for (const i of idx) { const l = lab[cellOf(g, xy[i]![0]![0]!, xy[i]![0]![1]!)]!, a = byComp.get(l); a ? a.push(i) : byComp.set(l, [i]) }
    comps.forEach((cells, id) => {
      const mem = byComp.get(id)
      if (!mem) return // closing-only cells cannot form a component of their own
      let sa = 0, sr = 0, zmin = Infinity
      for (const i of mem) { const f = all[i]!; sa += area[i]!; sr += area[i]! * (f.z! + f.h); zmin = Math.min(zmin, f.z!) }
      const top = sa > 0 ? sr / sa : mem.reduce((s, i) => s + all[i]!.z! + all[i]!.h, 0) / mem.length
      out.push({ group, mem, top, zmin, ...(outline ? { loops: traceLoops(cells, lab, id, g).map(l => l.map(([vx, vy]) => [g.x0 + vx! * cell, g.y0 + vy! * cell])) } : {}) })
    })
  }
  return out
}

/** A block as a footprint: outline simplified at eps/2, holes of at least eps x eps kept. */
function blockFeature(b: Block, eps: number, p: Projection, key: string): Footprint {
  const outer = b.loops!.filter(l => ringArea(l) > 0)
  if (outer.length !== 1) throw Error('Block component must have exactly one outer boundary')
  const simple = simplifyClosed(outer[0]!, eps / 2), ring = simple.length >= 3 && ringArea(simple) > 0 ? simple : outer[0]!
  const holes = b.loops!.filter(l => ringArea(l) < 0).map(l => simplifyClosed(l, eps / 2)).filter(l => l.length >= 3 && -ringArea(l) >= eps * eps)
  const ll = (r: number[][]) => { const x = r.map(q => toLL(p, q[0]!, q[1]!)); return [...x, x[0]!] }
  return { key, pnu: '', h: Math.max(b.top - b.zmin, 0.1), s: 'e', z: b.zmin, ring: ll(ring), ...(holes.length ? { holes: holes.map(ll) } : {}) }
}

/**
 * Buildings a merge at this level would misrepresent beyond its budget E = eps, by the same 3D bound as the measured
 * error: a member standing more than eps/2 above its block's roof (the outline may move another eps/2), and the tall
 * (h > E) members of a block that buries ground or lower roofs deeper than E inside its solid (e.g. a tower complex
 * closed into one slab). Up to three rounds, since pulling members out reshapes the blocks. At most
 * LANDMARKS_PER_BIN per (8 eps)^2 bin, largest error first.
 */
export function selectLandmarks(all: Footprint[], p: Projection, eps = REGION_LOD_EPS_METRES): Set<string> {
  const keys = new Set<string>()
  if (!all.length) return keys
  const prep = prepare(all, p, eps), perBin = new Map<string, number>(), size = 8 * eps
  const binOf = (i: number) => {
    const r = prep.xy[i]!, x = r.reduce((s, q) => s + q[0]!, 0) / r.length, y = r.reduce((s, q) => s + q[1]!, 0) / r.length
    return `${Math.floor(x / size)},${Math.floor(y / size)}`
  }
  const original = all.map(f => surfaceOf(f, p))
  for (let round = 0; round < 3; round++) {
    const rows = all.flatMap((f, i) => keys.has(f.key) ? [] : [i]), cand: { i: number; error: number }[] = []
    const blocks = mergeBlocks(all, prep, rows, true)
    const buried = buriedDepth(original, [...blocks.map((b, j) => surfaceOf(blockFeature(b, eps, p, `${j}`), p)), ...original.filter((_, i) => keys.has(all[i]!.key))], 2)
    blocks.forEach((b, j) => {
      for (const i of b.mem) {
        const f = all[i]!, excess = f.z! + f.h - b.top
        const error = Math.max(excess > eps / 2 ? excess + eps / 2 : 0, f.h > eps ? buried[j]! : 0)
        if (error > eps) cand.push({ i, error })
      }
    })
    cand.sort((a, b) => b.error - a.error || (all[a.i]!.key < all[b.i]!.key ? -1 : 1))
    let added = 0
    for (const { i } of cand) {
      const bin = binOf(i), n = perBin.get(bin) ?? 0
      if (n >= LANDMARKS_PER_BIN) continue
      perBin.set(bin, n + 1); keys.add(all[i]!.key); added++
    }
    if (!added) break
  }
  return keys
}
/** Per generalized item: deepest original point (roof, or ground) left inside its solid, as the 3D distance bound. */
function buriedDepth(A: Surface[], B: Surface[], cell: number) {
  const g = gridOver([...A, ...B].flatMap(s => s.rings), cell, cell), a = roofRaster(g, A), b = roofRaster(g, B)
  const out = edt(b.cover, g.W, g.H, 0), depth = new Float64Array(B.length)
  for (let i = 0; i < b.cover.length; i++) {
    if (!b.cover[i]) continue
    const s = a.cover[i] ? a.top[i]! : b.base[i]!
    if (s < b.top[i]!) depth[b.owner[i]!] = Math.max(depth[b.owner[i]!]!, Math.min(b.top[i]! - s, Math.sqrt(out.D[i]!) * cell + cell))
  }
  return depth
}

const inside = (rings: number[][][], x: number, y: number) => {
  let c = false
  for (const r of rings) for (let k = 0, n = r.length; k < n; k++) {
    const a = r[k]!, b = r[(k + 1) % n]!
    if ((a[1]! > y) !== (b[1]! > y) && x < a[0]! + (y - a[1]!) / (b[1]! - a[1]!) * (b[0]! - a[0]!)) c = !c
  }
  return c
}
const segDist = (x: number, y: number, a: number[], b: number[]) => {
  const dx = b[0]! - a[0]!, dy = b[1]! - a[1]!, L = dx * dx + dy * dy
  const t = L ? Math.max(0, Math.min(1, ((x - a[0]!) * dx + (y - a[1]!) * dy) / L)) : 0
  return Math.hypot(x - a[0]! - t * dx, y - a[1]! - t * dy)
}
/** Largest distance from a point of the box to the footprint (holes respected), sampled on <= ~4000 points, + one step. */
function boxDeviation(box: number[][], rings: number[][][]) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const q of box) { minX = Math.min(minX, q[0]!); minY = Math.min(minY, q[1]!); maxX = Math.max(maxX, q[0]!); maxY = Math.max(maxY, q[1]!) }
  const step = Math.max(1, Math.sqrt((maxX - minX) * (maxY - minY) / 4000))
  let worst = 0
  for (let y = minY + step / 2; y < maxY; y += step) for (let x = minX + step / 2; x < maxX; x += step) {
    if (!inside([box], x, y) || inside(rings, x, y)) continue
    let d = Infinity
    for (const r of rings) for (let k = 0; k < r.length; k++) d = Math.min(d, segDist(x, y, r[k]!, r[(k + 1) % r.length]!))
    worst = Math.max(worst, d)
  }
  return worst + step
}

export type GeneralizeStats = {
  eps: number; buildings: number; landmarks: number; landmarksObb: number; blocks: number; features: number
  hausdorffM: number; verticalP99M: number; verticalMaxM: number; geometricError: number
}
/** features[i] represents members[i] (input footprint keys); every input key appears in exactly one members list. */
export type GeneralizeResult = { features: Footprint[]; members: string[][]; stats: GeneralizeStats }

export function generalizeBuildings(all: Footprint[], p: Projection, eps = REGION_LOD_EPS_METRES, landmarkKeys?: Set<string>): GeneralizeResult {
  if (!(eps > 0) || !all.length) throw Error('Invalid generalization input')
  if (new Set(all.map(f => f.key)).size !== all.length) throw Error('Duplicate footprint key')
  for (const f of all) if (!Number.isFinite(f.z) || !Number.isFinite(f.h) || f.h <= 0 || f.ring.length < 3) throw Error(`Invalid footprint ${f.key}`)
  const marks = landmarkKeys ?? selectLandmarks(all, p, eps), prep = prepare(all, p, eps), { xy, area } = prep
  const features: Footprint[] = [], members: string[][] = []
  let landmarks = 0, landmarksObb = 0, blocks = 0
  const obb: { at: number; f: Footprint; rings: number[][][] }[] = []
  all.forEach((f, i) => {
    if (!marks.has(f.key)) return
    const o = coarseFootprint(f), oa = Math.abs(ringArea(o.ring.map(q => toXY(p, q))))
    if (oa <= 1.25 * area[i]! && Math.sqrt(oa) - Math.sqrt(area[i]!) < eps / 2)
      obb.push({ at: features.length, f: { ...o, key: `lm:${f.key}` }, rings: [xy[i]!, ...(f.holes ?? []).map(r => r.map(q => toXY(p, q)))] })
    landmarks++
    features.push({ ...f, key: `lm:${f.key}` }); members.push([f.key])
  })
  for (const b of mergeBlocks(all, prep, all.flatMap((f, i) => marks.has(f.key) ? [] : [i]), true)) {
    features.push(blockFeature(b, eps, p, `blk:${b.group}:${blocks}`))
    members.push(b.mem.map(i => all[i]!.key))
    blocks++
  }
  const original = all.map(f => surfaceOf(f, p))
  let measured = surfaceError(original, features.map(f => surfaceOf(f, p)), 2)
  // A box adds only its horizontal deviation from the footprint (its extra cells sit next to the same roof).
  const budget = Math.max(measured.hausdorffM, measured.verticalMaxM)
  for (const { at, f, rings } of obb) if (boxDeviation(f.ring.slice(0, -1).map(q => toXY(p, q)), rings) + 2 <= budget) { features[at] = f; landmarksObb++ }
  if (landmarksObb) measured = surfaceError(original, features.map(f => surfaceOf(f, p)), 2)
  const { hausdorffM, verticalP99M, verticalMaxM } = measured
  return { features, members, stats: { eps, buildings: all.length, landmarks, landmarksObb, blocks, features: features.length,
    hausdorffM, verticalP99M, verticalMaxM, geometricError: Math.max(hausdorffM, verticalMaxM) } }
}

/** Exact 1D squared distance transform (Felzenszwalb-Huttenlocher); arg[q] = index of the nearest site. */
function edt1(f: Float64Array, n: number, arg: Int32Array) {
  const d = new Float64Array(n), v = new Int32Array(n), z = new Float64Array(n + 1)
  let k = 0; v[0] = 0; z[0] = -Infinity; z[1] = Infinity
  for (let q = 1; q < n; q++) {
    let s = ((f[q]! + q * q) - (f[v[k]!]! + v[k]! * v[k]!)) / (2 * q - 2 * v[k]!)
    while (s <= z[k]!) { k--; s = ((f[q]! + q * q) - (f[v[k]!]! + v[k]! * v[k]!)) / (2 * q - 2 * v[k]!) }
    k++; v[k] = q; z[k] = s; z[k + 1] = Infinity
  }
  k = 0
  for (let q = 0; q < n; q++) { while (z[k + 1]! < q) k++; const r = v[k]!; d[q] = (q - r) ** 2 + f[r]!; arg[q] = r }
  return d
}
const FAR = 1e20
/** Squared cell distance to the nearest cell where mask === on, and that cell's index (feature transform). */
function edt(mask: Uint8Array, W: number, H: number, on = 1) {
  const D = new Float64Array(W * H), rowOf = new Int32Array(W * H), near = new Int32Array(W * H)
  for (let i = 0; i < D.length; i++) D[i] = mask[i] === on ? 0 : FAR
  const col = new Float64Array(H), ca = new Int32Array(H)
  for (let i = 0; i < W; i++) {
    for (let j = 0; j < H; j++) col[j] = D[j * W + i]!
    const r = edt1(col, H, ca)
    for (let j = 0; j < H; j++) { D[j * W + i] = r[j]!; rowOf[j * W + i] = ca[j]! }
  }
  const row = new Float64Array(W), ra = new Int32Array(W)
  for (let j = 0; j < H; j++) {
    for (let i = 0; i < W; i++) row[i] = D[j * W + i]!
    const r = edt1(row, W, ra)
    for (let i = 0; i < W; i++) { D[j * W + i] = r[i]!; near[j * W + i] = rowOf[j * W + ra[i]!]! * W + ra[i]! }
  }
  return { D, near }
}
type Surface = { rings: number[][][]; z: number; top: number }
const surfaceOf = (f: Footprint, p: Projection): Surface => ({ rings: [f.ring, ...(f.holes ?? [])].map(r => r.map(q => toXY(p, q))), z: f.z!, top: f.z! + f.h })
/** Highest roof per cell (holes respected), that roof's base and item; NaN where nothing covers the cell. */
function roofRaster(g: Grid, items: Surface[]) {
  const top = new Float64Array(g.W * g.H).fill(Number.NaN), base = new Float64Array(g.W * g.H), cover = new Uint8Array(g.W * g.H), owner = new Int32Array(g.W * g.H)
  for (const [k, s] of items.entries()) {
    let n = 0
    const put = (c: number) => { n++; if (!(s.top <= top[c]!)) { top[c] = s.top; base[c] = s.z; owner[c] = k } }
    rasterRings(g, s.rings, put)
    if (!n) put(cellOf(g, s.rings[0]![0]![0]!, s.rings[0]![0]![1]!)) // tiny footprints still count
  }
  for (let c = 0; c < cover.length; c++) if (!Number.isNaN(top[c]!)) cover[c] = 1
  return { top, base, cover, owner }
}
/**
 * Horizontal: symmetric Hausdorff distance between the two coverages, plus one cell of quantization.
 * Vertical: per cell covered by either side, an upper bound of the 3D distance from each side's top point there (its
 * roof, or the ground the other side covers) to the other scene (terrain + buildings); the larger of the two counts.
 * For a point p at height s over cell c and the other side O, each of these bounds the distance (+ one cell):
 *   straight up/down to O's top at c;
 *   p inside O's solid: straight out to the nearest cell O does not cover (the segment must cross O's surface), or
 *   to O's top (a surface point) at any O cell n: |c - n| + |s - O top at n|;
 *   p outside O's solid, any O cell n: |c - n| + max(0, s - O top at n) (top at or above s: the segment to (n, s)
 *   enters O's solid, so it crosses O's surface).
 * The last is first taken at the nearest O cell (feature transform), then searched outward only for the cells that
 * decide the maximum; the rest keep their first bound, which is never smaller.
 */
function surfaceError(A: Surface[], B: Surface[], cell: number) {
  const g = gridOver([...A, ...B].flatMap(s => s.rings), cell, cell), a = roofRaster(g, A), b = roofRaster(g, B)
  const ia = edt(a.cover, g.W, g.H), ib = edt(b.cover, g.W, g.H), oa = edt(a.cover, g.W, g.H, 0), ob = edt(b.cover, g.W, g.H, 0)
  type Side = typeof a
  type Field = typeof ia
  // Point of side P at cell i: its roof, or (uncovered) the ground under the other side's roof.
  const bound = (i: number, P: Side, O: Side, toO: Field, outO: Field, search: boolean) => {
    const s = P.cover[i] ? P.top[i]! : O.base[i]!, inO = O.cover[i] && s < O.top[i]!
    let d = Math.abs(s - (O.cover[i] ? O.top[i]! : P.base[i]!))
    // Inside O, O's top at any cell n is a surface point |s - top| above or below; outside, a top at or above s is
    // reached by crossing O's surface on the way to it.
    const rise = inO ? (t: number) => Math.abs(s - t) : (t: number) => Math.max(0, s - t)
    if (inO && outO.D[i]! < FAR) d = Math.min(d, Math.sqrt(outO.D[i]!) * cell + cell)
    if (toO.D[i]! < FAR) d = Math.min(d, Math.sqrt(toO.D[i]!) * cell + cell + rise(O.top[toO.near[i]!]!))
    if (!search) return d
    // Branch and bound over TILE x TILE tiles: skip a tile when its distance plus its least possible rise cannot win.
    const ci = i % g.W, cj = (i - ci) / g.W, ti = Math.floor(ci / TILE), tj = Math.floor(cj / TILE), T = O === a ? ta : tb
    for (const [di, dj, near] of tileOffsets(Math.ceil(d / cell / TILE) + 1)) {
      if (near * cell + cell >= d) break
      const ui = ti + di, uj = tj + dj
      if (ui < 0 || uj < 0 || ui >= T.W || uj >= T.H) continue
      const t = uj * T.W + ui, lo = T.lo[t]!, hi = T.hi[t]!
      if (Number.isNaN(lo)) continue
      const x0 = ui * TILE, y0 = uj * TILE, x1 = Math.min(g.W, x0 + TILE) - 1, y1 = Math.min(g.H, y0 + TILE) - 1
      const r0 = Math.hypot(Math.max(0, x0 - ci, ci - x1), Math.max(0, y0 - cj, cj - y1))
      const least = inO ? (s < lo ? lo - s : s > hi ? s - hi : 0) : Math.max(0, s - hi)
      if (r0 * cell + cell + least >= d) continue
      for (let jj = y0; jj <= y1; jj++) for (let ii = x0; ii <= x1; ii++) {
        const n = jj * g.W + ii
        if (O.cover[n]) d = Math.min(d, Math.hypot(ii - ci, jj - cj) * cell + cell + rise(O.top[n]!))
      }
    }
    return d
  }
  const ta = tiles(g, a), tb = tiles(g, b)
  const cellBound = (i: number, search: boolean) => Math.max(bound(i, a, b, ib, ob, search), bound(i, b, a, ia, oa, search))
  let m = 0, n = 0
  const idx = new Int32Array(a.cover.length), u = new Float64Array(a.cover.length)
  for (let i = 0; i < a.cover.length; i++) {
    if (a.cover[i] && ib.D[i]! > m) m = ib.D[i]!
    if (b.cover[i] && ia.D[i]! > m) m = ia.D[i]!
    if (a.cover[i] || b.cover[i]) { idx[n] = i; u[n++] = cellBound(i, false) }
  }
  // Refine in decreasing first bound until no unrefined cell can exceed the largest refined value: the maximum is
  // then exact for the refined bound (the 99th percentile mixes refined and first bounds, so it may overstate).
  // Order key: bound in 1/1024 m, then cell index.
  if (n >= 2 ** 22) throw Error('Error raster too large')
  const order = new Float64Array(n)
  for (let j = 0; j < n; j++) order[j] = Math.floor(u[j]! * 1024) * 2 ** 22 + j
  order.sort()
  let best = -1
  for (let t = n - 1; t >= 0; t--) {
    const j = order[t]! % 2 ** 22
    if (u[j]! <= best - 1 / 1024) break
    u[j] = cellBound(idx[j]!, true); best = Math.max(best, u[j]!)
  }
  const s = u.subarray(0, n).sort()
  return { hausdorffM: Math.sqrt(m) * cell + cell, verticalP99M: n ? s[Math.min(n - 1, Math.floor(n * 0.99))]! : 0, verticalMaxM: n ? s[n - 1]! : 0 }
}
const TILE = 8
/** Lowest and highest top per TILE x TILE tile (NaN: nothing covered). */
function tiles(g: Grid, side: { top: Float64Array; cover: Uint8Array }) {
  const W = Math.ceil(g.W / TILE), H = Math.ceil(g.H / TILE), lo = new Float64Array(W * H).fill(Number.NaN), hi = new Float64Array(W * H).fill(Number.NaN)
  for (let j = 0; j < g.H; j++) for (let i = 0; i < g.W; i++) {
    const c = j * g.W + i
    if (!side.cover[c]) continue
    const t = Math.floor(j / TILE) * W + Math.floor(i / TILE), v = side.top[c]!
    if (!(v >= lo[t]!)) lo[t] = v
    if (!(v <= hi[t]!)) hi[t] = v
  }
  return { W, H, lo, hi }
}
/** Tile offsets within radius r tiles, nearest first: [di, dj, lower bound of the cell distance between the tiles]. */
const offsetCache: [number, number, number][] = []
let offsetRadius = -1
function tileOffsets(r: number): [number, number, number][] {
  if (r <= offsetRadius) return offsetCache
  const out: [number, number, number][] = []
  for (let dj = -r; dj <= r; dj++) for (let di = -r; di <= r; di++) {
    const near = Math.hypot(Math.max(0, Math.abs(di) - 1), Math.max(0, Math.abs(dj) - 1)) * TILE
    if (near <= r * TILE) out.push([di, dj, near])
  }
  out.sort((x, y) => x[2] - y[2] || x[1] - y[1] || x[0] - y[0])
  offsetCache.length = 0; offsetCache.push(...out); offsetRadius = r
  return offsetCache
}
