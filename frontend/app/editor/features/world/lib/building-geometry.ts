export type Footprint = { key: string; pnu: string; ring: number[][]; h: number; s: 'm' | 'e' | 'u'; z?: number }
export type BuildingTile = { x: number; y: number; key: string }
export const BUILDING_ZOOM = 16
const N = 2 ** BUILDING_ZOOM

export function tileXY(lon: number, lat: number): [number, number] {
  const r = Math.max(-85, Math.min(85, lat)) * Math.PI / 180
  return [Math.floor((lon + 180) / 360 * N), Math.floor((1 - Math.asinh(Math.tan(r)) / Math.PI) / 2 * N)]
}

export function tilesIn(box: [number, number, number, number], focus: { lon: number; lat: number }): BuildingTile[] {
  const [cx, cy] = tileXY(focus.lon, focus.lat)
  const [x0, y1] = tileXY(box[0], box[1]), [x1, y0] = tileXY(box[2], box[3])
  const out: BuildingTile[] = []
  for (let x = Math.max(0, x0, cx - 8); x <= Math.min(N - 1, x1, cx + 8); x++) {
    for (let y = Math.max(0, y0, cy - 8); y <= Math.min(N - 1, y1, cy + 8); y++) out.push({ x, y, key: `${BUILDING_ZOOM}/${x}/${y}` })
  }
  return out.sort((a, b) => (a.x - cx) ** 2 + (a.y - cy) ** 2 - (b.x - cx) ** 2 - (b.y - cy) ** 2).slice(0, 40)
}

export function decodeBuildings(data: Uint8Array, tile: BuildingTile, Pbf: any, VectorTile: any): Footprint[] {
  const layer = new VectorTile(new Pbf(data)).layers.buildings
  const out: Footprint[] = []
  if (!layer) return out
  for (let i = 0; i < layer.length; i++) {
    const f = layer.feature(i), p = f.properties
    if (f.type !== 3 || !Number.isFinite(Number(p.h)) || Number(p.h) <= 0) continue
    for (const ring of f.loadGeometry()) {
      if (ring.length < 4) continue
      const area = ring.reduce((a: number, v: { x: number; y: number }, j: number) => {
        const next = ring[(j + 1) % ring.length]!
        return a + v.x * next.y - next.x * v.y
      }, 0)
      if (area <= 0) continue
      out.push({ key: `${tile.key}/${i}`, pnu: String(p.p ?? ''), h: Number(p.h), s: p.s === 'm' || p.s === 'e' ? p.s : 'u',
        z: p.z != null && Number.isFinite(Number(p.z)) ? Number(p.z) : undefined,
        ring: ring.map((v: { x: number; y: number }) => [(tile.x + v.x / f.extent) / N * 360 - 180,
          Math.atan(Math.sinh(Math.PI * (1 - 2 * (tile.y + v.y / f.extent) / N))) * 180 / Math.PI]) })
    }
  }
  return out
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
  const bounds = (r: number[][]) => [Math.min(...r.map(p => p[0]!)), Math.min(...r.map(p => p[1]!)), Math.max(...r.map(p => p[0]!)), Math.max(...r.map(p => p[1]!))]
  const aa = bounds(a.ring), bb = bounds(b.ring)
  if (aa[2]! < bb[0]! || bb[2]! < aa[0]! || aa[3]! < bb[1]! || bb[3]! < aa[1]!) return false
  if (a.ring.some(p => inside(p, b.ring)) || b.ring.some(p => inside(p, a.ring))) return true
  const cross = (p: number[], q: number[], r: number[]) => (q[0]! - p[0]!) * (r[1]! - p[1]!) - (q[1]! - p[1]!) * (r[0]! - p[0]!)
  for (let i = 1; i < a.ring.length; i++) for (let j = 1; j < b.ring.length; j++) {
    const p = a.ring[i - 1]!, q = a.ring[i]!, r = b.ring[j - 1]!, s = b.ring[j]!
    if (cross(p, q, r) * cross(p, q, s) < 0 && cross(r, s, p) * cross(r, s, q) < 0) return true
  }
  return a.ring.length === b.ring.length && a.ring.every((p, i) => p[0] === b.ring[i]![0] && p[1] === b.ring[i]![1])
}
