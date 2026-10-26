import type { BuildingMesh } from './building-mesh'

export type Footprint = { key: string; pnu: string; ring: number[][]; holes?: number[][][]; h: number; s: 'm' | 'e' | 'u'; z?: number; mesh?: BuildingMesh }
export type BuildingTile = { z: number; x: number; y: number; key: string }
export const BUILDING_ZOOM = 16

export type FootprintBounds = [number, number, number, number]
const boundsCache = new WeakMap<Footprint, FootprintBounds>()
export function footprintBounds(f: Footprint): FootprintBounds {
  const cached = boundsCache.get(f)
  if (cached) return cached
  const bounds: FootprintBounds = [Infinity, Infinity, -Infinity, -Infinity]
  for (const p of f.ring) {
    bounds[0] = Math.min(bounds[0], p[0]!); bounds[1] = Math.min(bounds[1], p[1]!)
    bounds[2] = Math.max(bounds[2], p[0]!); bounds[3] = Math.max(bounds[3], p[1]!)
  }
  // Decoded footprints are immutable; weak keys release cached bounds with their evicted tile.
  boundsCache.set(f, bounds)
  return bounds
}

export function tilesOverlap(a: BuildingTile, b: BuildingTile): boolean {
  const z = Math.min(a.z, b.z)
  return Math.floor(a.x / 2 ** (a.z - z)) === Math.floor(b.x / 2 ** (b.z - z))
    && Math.floor(a.y / 2 ** (a.z - z)) === Math.floor(b.y / 2 ** (b.z - z))
}

export function selectBuildingDetail(features: Footprint[], zoom: number): Footprint[] {
  if (zoom >= BUILDING_ZOOM) return features
  const limit = 160 * 2 ** (zoom - 13)
  if (features.length <= limit) return features
  const area = (f: Footprint) => {
    const [ox, oy] = f.ring[0]!
    return Math.abs(f.ring.reduce((sum, p, i) => {
      const q = f.ring[(i + 1) % f.ring.length]!
      return sum + (p[0]! - ox!) * (q[1]! - oy!) - (q[0]! - ox!) * (p[1]! - oy!)
    }, 0))
  }
  return features.map(f => ({ f, area: area(f) })).sort((a, b) => b.area - a.area).slice(0, limit).map(item => item.f)
}

export function tileXY(lon: number, lat: number, zoom = BUILDING_ZOOM): [number, number] {
  const N = 2 ** zoom
  const r = Math.max(-85, Math.min(85, lat)) * Math.PI / 180
  return [Math.floor((lon + 180) / 360 * N), Math.floor((1 - Math.asinh(Math.tan(r)) / Math.PI) / 2 * N)]
}

export function tilesIn(box: [number, number, number, number], focus: { lon: number; lat: number }): BuildingTile[] {
  let z = BUILDING_ZOOM
  const bounds = (zoom: number) => {
    const [x0, y1] = tileXY(box[0], box[1], zoom), [x1, y0] = tileXY(box[2], box[3], zoom)
    return { x0, y0, x1, y1 }
  }
  while (z > 13) {
    const b = bounds(z)
    if ((b.x1 - b.x0 + 1) * (b.y1 - b.y0 + 1) <= 40) break
    z--
  }
  const N = 2 ** z
  const [cx, cy] = tileXY(focus.lon, focus.lat, z)
  const { x0, y0, x1, y1 } = bounds(z)
  const out: BuildingTile[] = []
  // The archive stops at z13. Bound extreme globe views without enumerating millions of tiles.
  for (let x = Math.max(0, x0, cx - 16); x <= Math.min(N - 1, x1, cx + 16); x++) {
    for (let y = Math.max(0, y0, cy - 16); y <= Math.min(N - 1, y1, cy + 16); y++) out.push({ z, x, y, key: `${z}/${x}/${y}` })
  }
  return out.sort((a, b) => (a.x - cx) ** 2 + (a.y - cy) ** 2 - (b.x - cx) ** 2 - (b.y - cy) ** 2).slice(0, 256)
}

export async function decodeBuildings(data: Uint8Array, tile: BuildingTile, Pbf: any, VectorTile: any, signal?: AbortSignal): Promise<Footprint[]> {
  const N = 2 ** tile.z
  const layer = new VectorTile(new Pbf(data)).layers.buildings
  const out: Footprint[] = []
  if (!layer) return out
  let deadline = performance.now() + 2
  for (let i = 0; i < layer.length; i++) {
    signal?.throwIfAborted()
    if (performance.now() >= deadline) {
      await new Promise(resolve => setTimeout(resolve, 0))
      signal?.throwIfAborted()
      deadline = performance.now() + 2
    }
    const f = layer.feature(i), p = f.properties
    if (f.type !== 3 || !Number.isFinite(Number(p.h)) || Number(p.h) <= 0) continue
    let exterior: Footprint | undefined
    for (const ring of f.loadGeometry()) {
      if (ring.length < 4) continue
      const area = ring.reduce((a: number, v: { x: number; y: number }, j: number) => {
        const next = ring[(j + 1) % ring.length]!
        return a + v.x * next.y - next.x * v.y
      }, 0)
      if (area === 0) continue
      const coordinates = ring.map((v: { x: number; y: number }) => [(tile.x + v.x / f.extent) / N * 360 - 180,
        Math.atan(Math.sinh(Math.PI * (1 - 2 * (tile.y + v.y / f.extent) / N))) * 180 / Math.PI])
      // MVT interior rings follow the exterior they belong to, including multipolygons.
      if (area < 0) {
        if (exterior) (exterior.holes ??= []).push(coordinates)
        continue
      }
      exterior = { key: `${tile.key}/${i}`, pnu: String(p.p ?? ''), h: Number(p.h), s: p.s === 'm' || p.s === 'e' ? p.s : 'u',
        z: p.z != null && Number.isFinite(Number(p.z)) ? Number(p.z) : undefined,
        ring: coordinates }
      out.push(exterior)
    }
  }
  return selectBuildingDetail(out, tile.z)
}

export function inside(point: number[], ring: number[][]): boolean {
  let hit = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i]!, b = ring[j]!
    if ((a[1]! > point[1]!) !== (b[1]! > point[1]!) && point[0]! < (b[0]! - a[0]!) * (point[1]! - a[1]!) / (b[1]! - a[1]!) + a[0]!) hit = !hit
  }
  return hit
}

export function overlaps(a: Footprint, b: Footprint): boolean {
  const aa = footprintBounds(a), bb = footprintBounds(b)
  if (aa[2]! < bb[0]! || bb[2]! < aa[0]! || aa[3]! < bb[1]! || bb[3]! < aa[1]!) return false
  if (a.ring.some(p => insideFootprint(p, b)) || b.ring.some(p => insideFootprint(p, a))) return true
  const cross = (p: number[], q: number[], r: number[]) => (q[0]! - p[0]!) * (r[1]! - p[1]!) - (q[1]! - p[1]!) * (r[0]! - p[0]!)
  for (const ar of [a.ring, ...(a.holes ?? [])]) for (const br of [b.ring, ...(b.holes ?? [])]) {
    for (let i = 0; i < ar.length; i++) for (let j = 0; j < br.length; j++) {
      const p = ar[i]!, q = ar[(i + 1) % ar.length]!, r = br[j]!, s = br[(j + 1) % br.length]!
      if (cross(p, q, r) * cross(p, q, s) < 0 && cross(r, s, p) * cross(r, s, q) < 0) return true
    }
  }
  return a.ring.length === b.ring.length && a.ring.every((p, i) => p[0] === b.ring[i]![0] && p[1] === b.ring[i]![1])
}

export function insideFootprint(point: number[], f: Footprint): boolean {
  return inside(point, f.ring) && !(f.holes?.some(hole => inside(point, hole)))
}
