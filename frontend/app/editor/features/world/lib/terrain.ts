/**
 * Terrain from SiteContext's NGII DEM, as a Cesium heightmap terrain: each tile asks the backend for a 17 x 17 grid
 * (rows north to south). Far-away tiles (coarse levels) and anything the DEM cannot answer stand flat at the
 * fallback height, so a missing tile shows as flat ground, never as a hole or a made-up slope.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
const SIZE = 17
const MIN_LEVEL = 13   // ~2.4 km tiles; coarser (far-away) tiles stand flat at the fallback height
const MAX_LEVEL = 15   // ~600 m tiles, ~37 m between samples; finer levels reuse (upsample) their level-15 parent
// At most this many tile requests at once: the browser has ~6 connections per host and the context layers need some.
const IN_FLIGHT = 2
const KOREA = { west: 124, south: 33, east: 132, north: 39 }

export function demTerrain(Cesium: any, fallback: () => number): any {
  let running = 0
  let disposed = false
  const waiting: (() => void)[] = []
  const slot = () => new Promise<void>((go) => { if (running < IN_FLIGHT) { running++; go() } else waiting.push(() => { running++; go() }) })
  const release = () => { running--; waiting.shift()?.() }
  const flat = () => new Float32Array(SIZE * SIZE).fill(fallback())
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
      return slot()
        .then(() => (disposed ? Promise.reject(new Error('terrain replaced')) : fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/terrain-heights?${query}`)))
        .then((res: Response) => (res.ok ? res.json() : Promise.reject(new Error(String(res.status)))))
        .then((body) => (Array.isArray(body.heights) && body.heights.length === SIZE * SIZE ? new Float32Array(body.heights) : flat()))
        .catch(() => flat())
        .finally(release)
    },
  })
  // replaced or unmounted: queued tiles resolve flat without fetching
  provider.dispose = () => { disposed = true }
  return provider
}
