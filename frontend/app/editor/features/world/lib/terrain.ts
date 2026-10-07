/**
 * Terrain from SiteContext's NGII DEM, as a Cesium heightmap terrain: each tile asks the backend for a 33 x 33 grid
 * (rows north to south). A tile the DEM cannot answer is filled from the nearest coarser tile it did answer
 * (the same DEM, sampled wider) — filling it flat at the fallback height cut 60-100 m cliffs into the ground and hung
 * masses on their edges. Far-away tiles (coarser than MIN_LEVEL) and tiles with no answered ancestor stand flat at the
 * fallback height, never as a hole or a made-up slope.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
const SIZE = 33     // the backend maximum; as fast as 17 x 17 (~5 s a tile) and a terrace edge smears half as far
const MIN_LEVEL = 12   // ~4.9 km tiles (the backend takes boxes up to 0.1 deg); coarser (far-away) tiles stand flat
const MAX_LEVEL = 15   // ~600 m tiles, ~18 m between samples; finer levels reuse (upsample) their level-15 parent
// At most this many tile requests at once: the browser has ~6 connections per host and the context layers need some.
const IN_FLIGHT = 2
const KOREA = { west: 124, south: 33, east: 132, north: 39 }
const KEEP = 2000      // answered tiles kept to fill refused children from (~1.2 kB each)

/** The heights of tile (x, y, level) read off an answered ancestor tile, bilinear; null when no ancestor answered. */
function fromAncestor(answered: Map<string, Float32Array>, x: number, y: number, level: number): Float32Array | null {
  for (let d = 1; level - d >= MIN_LEVEL; d++) {
    const ax = x >> d, ay = y >> d, h = answered.get(`${level - d}/${ax}/${ay}`)
    if (!h) continue
    const n = 2 ** d, ox = x - ax * n, oy = y - ay * n, out = new Float32Array(SIZE * SIZE), last = SIZE - 1
    for (let j = 0; j < SIZE; j++) {
      for (let i = 0; i < SIZE; i++) {
        const fx = ((ox + i / last) / n) * last, fy = ((oy + j / last) / n) * last
        const c = Math.min(Math.floor(fx), last - 1), r = Math.min(Math.floor(fy), last - 1), u = fx - c, v = fy - r
        out[j * SIZE + i] = h[r * SIZE + c]! * (1 - u) * (1 - v) + h[r * SIZE + c + 1]! * u * (1 - v)
          + h[(r + 1) * SIZE + c]! * (1 - u) * v + h[(r + 1) * SIZE + c + 1]! * u * v
      }
    }
    return out
  }
  return null
}

/** `focus`: where the camera looks. A tile takes 5-12 s and Cesium asks for tiles out to the horizon, so waiting
 *  tiles are served nearest to the focus first — in arrival order the ground under the camera waited for minutes. */
export function demTerrain(Cesium: any, fallback: () => number, focus: () => { lon: number; lat: number } | null = () => null): any {
  let running = 0
  let disposed = false
  const waiting: { lon: number; lat: number; go: () => void }[] = []
  const slot = (lon: number, lat: number) => new Promise<void>((go) => {
    if (running < IN_FLIGHT) { running++; go() } else waiting.push({ lon, lat, go: () => { running++; go() } })
  })
  const release = () => {
    running--
    if (!waiting.length) return
    const f = focus()
    let best = 0
    if (f) {
      const d = (w: { lon: number; lat: number }) => ((w.lon - f.lon) * Math.cos((f.lat * Math.PI) / 180)) ** 2 + (w.lat - f.lat) ** 2
      waiting.forEach((w, i) => { if (d(w) < d(waiting[best]!)) best = i })
    }
    waiting.splice(best, 1)[0]!.go()
  }
  const flat = () => new Float32Array(SIZE * SIZE).fill(fallback())
  const answered = new Map<string, Float32Array>()
  const keep = (key: string, h: Float32Array) => {
    answered.set(key, h)
    if (answered.size > KEEP) answered.delete(answered.keys().next().value!)
    return h
  }
  // a gateway hiccup (502/504, dropped connection) is asked once more; a refusal (the DEM does not reach) is not
  const ask = (query: URLSearchParams, again: boolean): Promise<Float32Array> =>
    (disposed ? Promise.reject(new Error('terrain replaced')) : fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/terrain-heights?${query}`))
      .then((res: Response) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
      .then((body) => (Array.isArray(body.heights) && body.heights.length === SIZE * SIZE ? new Float32Array(body.heights) : Promise.reject(new Error('no heights'))))
      .catch((e: Error) => (again && !disposed && (/^5\d\d$/.test(e.message) || e instanceof TypeError) ? ask(query, false) : Promise.reject(e)))
  const provider = new Cesium.CustomHeightmapTerrainProvider({
    width: SIZE,
    height: SIZE,
    callback: (x: number, y: number, level: number) => {
      if (level > MAX_LEVEL) return undefined
      if (level < MIN_LEVEL) return flat()
      const r = provider.tilingScheme.tileXYToRectangle(x, y, level)
      const [west, south, east, north] = [r.west, r.south, r.east, r.north].map((v: number) => Cesium.Math.toDegrees(v))
      if (west < KOREA.west || east > KOREA.east || south < KOREA.south || north > KOREA.north) return flat()
      const query = new URLSearchParams({ west: String(west), south: String(south), east: String(east), north: String(north), size: String(SIZE) })
      const key = `${level}/${x}/${y}`
      return slot((west + east) / 2, (south + north) / 2)
        .then(() => ask(query, true))
        .then((h) => keep(key, h))
        .catch(() => fromAncestor(answered, x, y, level) ?? flat())
        .finally(release)
    },
  })
  // replaced or unmounted: queued tiles resolve flat without fetching
  provider.dispose = () => { disposed = true }
  return provider
}
