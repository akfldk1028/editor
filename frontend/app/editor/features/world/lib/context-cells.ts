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

/** The ground box the camera sees, clipped around the screen centre so a low, tilted view does not reach the horizon. */
export function visibleBox(viewer: any, Cesium: any): { box: [number, number, number, number]; focus: { lat: number; lon: number } } | null {
  const canvas = viewer.canvas
  const pick = (x: number, y: number) => {
    const p = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(x, y))
    if (!p) return null
    const c = Cesium.Cartographic.fromCartesian(p)
    return { lat: Cesium.Math.toDegrees(c.latitude), lon: Cesium.Math.toDegrees(c.longitude) }
  }
  const centre = pick(canvas.clientWidth / 2, canvas.clientHeight / 2)
  if (!centre) return null
  const pts = ([[0.1, 0.3], [0.9, 0.3], [0.1, 0.98], [0.9, 0.98], [0.5, 0.5]] as [number, number][])
    .map(([x, y]) => pick(canvas.clientWidth * x, canvas.clientHeight * y)).filter(Boolean) as { lat: number; lon: number }[]
  const lim = 0.012 // never more than ~1.3 km from the centre
  const lats = pts.map((p) => Math.min(Math.max(p.lat, centre.lat - lim), centre.lat + lim))
  const lons = pts.map((p) => Math.min(Math.max(p.lon, centre.lon - lim), centre.lon + lim))
  return { box: [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)], focus: centre }
}
