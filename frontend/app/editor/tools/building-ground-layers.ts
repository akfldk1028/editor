import { createHash } from 'node:crypto'
import type { Footprint } from '../features/world/lib/building-geometry'
import type { GroundSample, GroundSource } from './building-ground-publication'

export type GroundLayer = {
  revision: string
  sample: (points: number[][]) => Promise<GroundSample>
  verify?: () => Promise<void>
}
type LayerName = 'base' | 'precise'
type Assignment = LayerName | 'existing' | 'missing'

export function canResumeLayeredGround(region: { groundPolicy?: string; groundRevision?: string }, revision: string) {
  return region.groundPolicy === 'layered-ground-v1' && region.groundRevision === revision
}

export function layeredGroundRevision(revisions: { base?: string; precise?: string }) {
  return createHash('sha256').update(JSON.stringify([
    'layered-ground-v1', revisions.base ?? null, revisions.precise ?? null,
  ])).digest('hex')
}

export async function enrichLayeredGround(features: Footprint[], layers: { base?: GroundLayer; precise?: GroundLayer }) {
  const staged = features.map(f => f.z)
  const assignments: Assignment[] = features.map(f => Number.isFinite(f.z) ? 'existing' : 'missing')
  const beforeMissing = assignments.filter(value => value === 'missing').length
  const sources: Partial<Record<LayerName, GroundSource>> = {}
  let preciseOverride = 0
  for (const name of ['base', 'precise'] as const) {
    const layer = layers[name]
    if (!layer) continue
    if (!layer.revision) throw new Error('Missing DEM source revision')
    const indices = features.map((_, i) => i).filter(i => name === 'precise' || !Number.isFinite(staged[i]))
    for (let start = 0; start < indices.length; start += 1024) {
      const batch = indices.slice(start, start + 1024)
      const result = await layer.sample(batch.map(i => features[i]!.ring[0]!))
      if (result.source?.fileSignature !== layer.revision) throw new Error(`${name} DEM source changed during publication`)
      if (!Array.isArray(result.heights) || result.heights.length !== batch.length) throw new Error('Invalid DEM result')
      sources[name] = result.source
      for (let offset = 0; offset < batch.length; offset++) {
        const z = result.heights[offset], index = batch[offset]!
        if (typeof z !== 'number' || !Number.isFinite(z) || z < -500 || z > 9000) continue
        if (name === 'precise' && Number.isFinite(staged[index])) preciseOverride++
        staged[index] = z
        assignments[index] = name
      }
    }
  }
  // A later layer can take long enough for an earlier source to change on disk.
  for (const layer of [layers.base, layers.precise]) await layer?.verify?.()
  const remaining = staged.filter(z => !Number.isFinite(z)).length
  features.forEach((feature, index) => {
    if (assignments[index] === 'base' || assignments[index] === 'precise') feature.z = staged[index]
  })
  return {
    policy: 'layered-ground-v1' as const,
    fileSignature: layeredGroundRevision({ base: layers.base?.revision, precise: layers.precise?.revision }),
    priority: ['precise', 'existing', 'base'] as const,
    revisions: { base: layers.base?.revision, precise: layers.precise?.revision },
    sources, assignments,
    metrics: { beforeMissing, newlyFilled: beforeMissing - remaining, preciseOverride, remaining },
  }
}
