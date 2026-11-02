import type { Footprint } from '../features/world/lib/building-geometry'

export type GroundSource = { fileSignature: string; [key: string]: unknown }
export type GroundSample = { heights: (number | null)[]; source: GroundSource }

export function selectGroundLeaves(input: Map<string, Footprint[]>) {
  const leaves = new Map<string, Footprint[]>(), all: Footprint[] = []
  const coverage: string[] = [], partialCoverage: string[] = []
  for (const [key, features] of input) {
    const ready = features.filter(f => Number.isFinite(f.z))
    leaves.set(key, ready)
    all.push(...ready)
    if (ready.length === features.length) coverage.push(key)
    else if (ready.length) partialCoverage.push(key)
  }
  return { leaves, all, coverage, partialCoverage }
}

export function canResumeGround(region: { groundPolicy?: string; groundRevision?: string }, revision: string) {
  return region.groundPolicy === 'archive'
    || region.groundPolicy === 'local-dem' && region.groundRevision === revision
}

export async function enrichGround(features: Footprint[], revision: string,
  sample: (points: number[][]) => Promise<GroundSample>): Promise<GroundSource | undefined> {
  // Archive datums are not tagged as DEM-derived. Only replace our own missing-datum enrichment.
  const missing = features.filter(f => !Number.isFinite(f.z))
  const heights: (number | null)[] = []
  let source: GroundSource | undefined
  for (let start = 0; start < missing.length; start += 1024) {
    const batch = missing.slice(start, start + 1024)
    const result = await sample(batch.map(f => f.ring[0]!))
    if (result.source?.fileSignature !== revision) throw new Error('DEM source changed during publication')
    if (!Array.isArray(result.heights) || result.heights.length !== batch.length) throw new Error('Invalid DEM result')
    source = result.source
    heights.push(...result.heights)
  }
  heights.forEach((z, i) => {
    if (typeof z === 'number' && Number.isFinite(z) && z >= -500 && z <= 9000) missing[i]!.z = z
  })
  return source
}
