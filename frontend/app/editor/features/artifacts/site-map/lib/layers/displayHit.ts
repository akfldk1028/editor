import type { LngLat } from '../engine/types'
import { containsPoint } from './parcelOutline'

export type DisplayHit = { source: LngLat[]; displayed: LngLat[] }
const polygon = (ring: LngLat[]) => ({ type: 'Polygon', coordinates: [ring] })

export function resolveDisplayHit(at: LngLat, hits: readonly DisplayHit[]): LngLat {
  for (const { source, displayed } of hits) {
    if (!containsPoint(polygon(displayed), at)) continue
    if (containsPoint(polygon(source), at)) return at
    // Resolve identity inside the original parcel, not at its shifted visual boundary.
    const y = (Math.min(...source.map(p => p[1])) + Math.max(...source.map(p => p[1]))) / 2
    const crossings: number[] = []
    for (let i = 0; i < source.length - 1; i++) {
      const a = source[i]!, b = source[i + 1]!
      if ((a[1] > y) !== (b[1] > y)) crossings.push(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]))
    }
    crossings.sort((a, b) => a - b)
    for (let i = 0; i + 1 < crossings.length; i += 2) {
      const candidate: LngLat = [(crossings[i]! + crossings[i + 1]!) / 2, y]
      if (containsPoint(polygon(source), candidate)) return candidate
    }
  }
  return at
}
