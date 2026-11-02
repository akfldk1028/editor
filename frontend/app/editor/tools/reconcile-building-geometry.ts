import type { Footprint } from '../features/world/lib/building-geometry'

export function reconcilePublishedGeometry(published: Footprint[], decoded: Footprint[]): Footprint[] {
  const validRing = (ring: number[][]) => Array.isArray(ring) && ring.length >= 3
    && ring.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))
  const validShape = (f: Footprint) => typeof f.key === 'string' && validRing(f.ring)
    && (f.holes === undefined || Array.isArray(f.holes) && f.holes.every(validRing))
  const component = (f: Footprint) => JSON.stringify([f.key, f.ring])
  const topology = (f: Footprint) => JSON.stringify(f.holes ?? [])
  const sources = new Map<string, Footprint>()
  for (const source of decoded) {
    if (!validShape(source)) throw new Error(`Invalid decoded component ${source.key}`)
    const id = component(source), existing = sources.get(id)
    if (existing && topology(existing) !== topology(source)) throw new Error(`Ambiguous decoded component ${source.key}`)
    sources.set(id, source)
  }
  const seen = new Set<string>()
  return published.map(previous => {
    if (!validShape(previous) || !Number.isFinite(previous.z) || !Number.isFinite(previous.h) || previous.h <= 0) {
      throw new Error(`Invalid published component ${previous.key}`)
    }
    const id = component(previous)
    if (seen.has(id)) throw new Error(`Duplicate published component ${previous.key}`)
    seen.add(id)
    const source = sources.get(id)
    if (!source) throw new Error(`Missing decoded component ${previous.key}`)
    if (previous.holes?.length && topology(previous) !== topology(source)) {
      throw new Error(`Published holes differ from decoded component ${previous.key}`)
    }
    // Publication owns all elevations and identities; raw data supplies only missing topology.
    const next = structuredClone(previous)
    if (source.holes?.length) next.holes = structuredClone(source.holes)
    return next
  })
}
