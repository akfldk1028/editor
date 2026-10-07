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

/** How a parcel is drawn: the searched site, a clicked pick, or the saved selection. */
export type ParcelLook = 'site' | 'picked' | 'saved'

/** Thin fill for picks in the shell's accent (--accent), so the map's own colours still show through. */
export const selectionFill = { color: '#d97757', picked: 0.15, saved: 0.22 } as const

/** The merged boundary of a multi-parcel site (합필 경계). */
export const mergedOutline = { width: 3.5 } as const

/** The hover preview: a faint 1px outline. */
export const hoverOutline = { color: parcelOutline.color, width: 1, opacity: 0.55 } as const

export interface ParcelStyle { width: number; dashed: boolean; fillOpacity: number }

/** Site: dashed, no fill. Pick: dashed 2px over a light fill. Saved: solid 2px, a little more fill. */
export function parcelStyle(look: ParcelLook): ParcelStyle {
  if (look === 'picked') return { width: 2, dashed: true, fillOpacity: selectionFill.picked }
  if (look === 'saved') return { width: 2, dashed: false, fillOpacity: selectionFill.saved }
  return { width: parcelOutline.width, dashed: true, fillOpacity: 0 }
}

/** `#rrggbb` → `rgba(…)` for providers that take one colour string. */
export function rgba(hex: string, alpha: number): string {
  const value = Number.parseInt(hex.slice(1), 16)
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`
}

/** Whether the point lies inside the parcel (even-odd over all rings, so holes count). */
export function containsPoint(geojson: unknown, [lng, lat]: LngLat): boolean {
  let inside = false
  for (const ring of parcelRings(geojson)) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i]!
      const [xj, yj] = ring[j]!
      if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside
    }
  }
  return inside
}

/** The 지번 part of a parcel address ("… 산곡동 684-1" → "684-1"). */
export function lotLabel(address: string, pnu: string): string {
  const tail = address.trim().match(/(산\s*)?\d+(-\d+)?$/)
  if (tail) return tail[0].replace(/\s+/g, '')
  const main = Number(pnu.slice(11, 15))
  const sub = Number(pnu.slice(15, 19))
  return `${pnu[10] === '2' ? '산' : ''}${main}${sub ? `-${sub}` : ''}`
}
