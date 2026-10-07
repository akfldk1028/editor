import type { LngLat } from '../engine/types'

/** The selected parcel: a red dashed outline, no fill (the map's colours stay visible). */
export const parcelOutline = {
  color: '#ef4444',
  width: 2.5,
  /** Dash and gap in px. */
  dash: [8, 6] as const,
} as const

type Ring = LngLat[]

/** Outer and inner rings of a Polygon, MultiPolygon, Feature or FeatureCollection, in lon/lat. */
export function parcelRings(geojson: unknown): Ring[] {
  if (!geojson || typeof geojson !== 'object') return []
  const value = geojson as { type?: string; coordinates?: unknown; geometry?: unknown; features?: unknown[] }
  switch (value.type) {
    case 'FeatureCollection':
      return (value.features ?? []).flatMap(parcelRings)
    case 'Feature':
      return parcelRings(value.geometry)
    case 'Polygon':
      return (value.coordinates as number[][][]).map(toRing)
    case 'MultiPolygon':
      return (value.coordinates as number[][][][]).flatMap((polygon) => polygon.map(toRing))
    default:
      return []
  }
}

function toRing(ring: number[][]): Ring {
  return ring.map(([lng, lat]) => [lng!, lat!] as const)
}

/** [west, south, east, north] of the rings, or null when there are none. */
export function parcelBounds(rings: readonly Ring[]): [number, number, number, number] | null {
  const points = rings.flat()
  if (points.length === 0) return null
  const lngs = points.map(([lng]) => lng)
  const lats = points.map(([, lat]) => lat)
  return [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)]
}

export function boundsCenter([west, south, east, north]: readonly [number, number, number, number]): LngLat {
  return [(west + east) / 2, (south + north) / 2]
}
