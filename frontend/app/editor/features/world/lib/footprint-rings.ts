import type { Footprint } from './building-geometry'

export function footprintRings(feature: Footprint): number[][][] {
  const clean = (source: number[][], interior: boolean) => {
    const ring = source.filter((p, i) => !i || p[0] !== source[i - 1]![0] || p[1] !== source[i - 1]![1])
    if (ring.length > 1 && ring[0]![0] === ring.at(-1)![0] && ring[0]![1] === ring.at(-1)![1]) ring.pop()
    if (ring.length < 3) return []
    const [ox, oy] = ring[0]!
    const area = ring.reduce((sum, p, i) => {
      const q = ring[(i + 1) % ring.length]!
      return sum + (p[0]! - ox!) * (q[1]! - oy!) - (q[0]! - ox!) * (p[1]! - oy!)
    }, 0)
    if (Math.abs(area) < 1e-15) return []
    // CCW exteriors and CW interiors put both wall normals outside the solid.
    if ((area < 0) !== interior) ring.reverse()
    return ring
  }
  const exterior = clean(feature.ring, false)
  return exterior.length ? [exterior, ...(feature.holes ?? []).map(r => clean(r, true)).filter(r => r.length)] : []
}
