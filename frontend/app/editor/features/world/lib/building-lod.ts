import { tileXY, tilesOverlap, type BuildingTile } from './building-geometry'

export type BuildingView = { lon: number; lat: number; height: number; pixels: number; fov: number }
const tile = (z: number, x: number, y: number): BuildingTile => ({ z, x, y, key: `${z}/${x}/${y}` })
const latitude = (y: number, n: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI

/** Mixed quadtree levels: spend the tile budget on projected detail, keeping parents wherever refinement cannot fit. */
export function lodTiles(box: [number, number, number, number], focus: { lon: number; lat: number },
  view: BuildingView, previous: BuildingTile[] = []): BuildingTile[] {
  const bounds = (t: BuildingTile) => {
    const n = 2 ** t.z
    return [t.x / n * 360 - 180, latitude(t.y + 1, n), (t.x + 1) / n * 360 - 180, latitude(t.y, n)]
  }
  const intersects = (t: BuildingTile) => {
    const [w, s, e, n] = bounds(t)
    return w! <= box[2] && e! >= box[0] && s! <= box[3] && n! >= box[1]
  }
  const [x0, y1] = tileXY(box[0], box[1], 13), [x1, y0] = tileXY(box[2], box[3], 13)
  const [cx, cy] = tileXY(focus.lon, focus.lat, 13)
  const leaves: BuildingTile[] = []
  for (let x = Math.max(0, x0, cx - 16); x <= Math.min(8191, x1, cx + 16); x++)
    for (let y = Math.max(0, y0, cy - 16); y <= Math.min(8191, y1, cy + 16); y++) leaves.push(tile(13, x, y))
  const distance = (t: BuildingTile) => {
    const b = bounds(t)
    return Math.hypot(((b[0]! + b[2]!) / 2 - focus.lon) * Math.cos(focus.lat * Math.PI / 180), (b[1]! + b[3]!) / 2 - focus.lat)
  }
  leaves.sort((a, b) => distance(a) - distance(b))
  leaves.splice(256)
  const budget = leaves.length <= 48 ? 96 : leaves.length + 64
  const error = (t: BuildingTile) => {
    const [w, s, e, n] = bounds(t), scale = 111320 * Math.cos(view.lat * Math.PI / 180)
    const dx = (view.lon - Math.max(w!, Math.min(e!, view.lon))) * scale
    const dy = (view.lat - Math.max(s!, Math.min(n!, view.lat))) * 111320
    const range = Math.max(1, Math.hypot(dx, dy, Math.max(1, view.height)))
    // The archive has no geometric-error metadata; 1/32 tile width is a conservative display heuristic.
    return (e! - w!) * scale / 32 * view.pixels / (2 * Math.tan(view.fov / 2) * range)
  }
  while (leaves.length < budget) {
    const candidates = leaves.filter(t => t.z < 16).map(t => ({ t, error: error(t),
      threshold: previous.some(p => p.z > t.z && tilesOverlap(p, t)) ? 6 : 10 }))
      .filter(c => c.error > c.threshold).sort((a, b) => b.error - a.error)
    let split = false
    for (const { t } of candidates) {
      const children = [tile(t.z + 1, t.x * 2, t.y * 2), tile(t.z + 1, t.x * 2 + 1, t.y * 2),
        tile(t.z + 1, t.x * 2, t.y * 2 + 1), tile(t.z + 1, t.x * 2 + 1, t.y * 2 + 1)].filter(intersects)
      if (!children.length || leaves.length + children.length - 1 > budget) continue
      leaves.splice(leaves.indexOf(t), 1, ...children); split = true; break
    }
    if (!split) break
  }
  return leaves.sort((a, b) => distance(a) - distance(b))
}
