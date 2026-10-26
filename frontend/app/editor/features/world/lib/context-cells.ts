/**
 * Load the context the camera sees, cell by cell: the ground is cut into ~440 m cells and each cell is asked
 * once (a circle around its centre that covers it). Overlapping replies are de-duplicated by building id.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
export const CELL_LAT = 0.004 // ≈ 445 m
export const CELL_LON = 0.005 // ≈ 440 m at 37.5°N
export const CELL_RADIUS_M = 320 // half-diagonal of a cell, so the circle covers it
export const MAX_CELLS = 30 // one camera move never asks for more than this
export const MAX_ALTITUDE_M = 4000 // above this the masses are too small to matter: nothing is asked

export interface Cell { key: string; lat: number; lon: number }

/** Cells inside a [west, south, east, north] box (degrees), nearest to the focus first. */
export function cellsIn(box: [number, number, number, number], focus: { lat: number; lon: number }): Cell[] {
  const [w, s, e, n] = box
  const out: Cell[] = []
  for (let i = Math.floor(s / CELL_LAT); i <= Math.floor(n / CELL_LAT); i++) {
    for (let j = Math.floor(w / CELL_LON); j <= Math.floor(e / CELL_LON); j++) {
      out.push({ key: `${i}:${j}`, lat: (i + 0.5) * CELL_LAT, lon: (j + 0.5) * CELL_LON })
    }
  }
  const d = (c: Cell) => (c.lat - focus.lat) ** 2 + ((c.lon - focus.lon) * 0.79) ** 2
  return out.sort((a, b) => d(a) - d(b))
}

/** Sample the screen edges, including the horizon when the upper part of the screen is sky. */
export function visibleBox(viewer: any, Cesium: any): { box: [number, number, number, number]; focus: { lat: number; lon: number } } | null {
  const canvas = viewer.canvas
  const pick = (x: number, y: number) => {
    const p = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(x, y))
    if (!p) return null
    const c = Cesium.Cartographic.fromCartesian(p)
    return { lat: Cesium.Math.toDegrees(c.latitude), lon: Cesium.Math.toDegrees(c.longitude) }
  }
  const centre = pick(canvas.clientWidth / 2, canvas.clientHeight / 2) ?? pick(canvas.clientWidth / 2, canvas.clientHeight * 0.98)
  if (!centre) return null
  const pts = [centre]
  for (const x of [0, 0.5, 1]) {
    let sky: number | null = null
    for (const y of [0, 0.25, 0.5, 0.75, 1]) {
      const p = pick(canvas.clientWidth * x, canvas.clientHeight * y)
      if (!p) { sky = y; continue }
      pts.push(p)
      if (sky !== null) {
        let lo = sky, hi = y
        for (let i = 0; i < 10; i++) {
          const mid = (lo + hi) / 2
          const edge = pick(canvas.clientWidth * x, canvas.clientHeight * mid)
          if (edge) { hi = mid; pts.push(edge) } else lo = mid
        }
        sky = null
      }
    }
  }
  const lats = pts.map(p => p.lat), lons = pts.map(p => p.lon)
  return { box: [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)], focus: centre }
}
