import { createHash } from 'node:crypto'
import type { Footprint } from '../features/world/lib/building-geometry'
import type { GroundLayer } from './building-ground-layers'

export const COMPOSED_GROUND_POLICY = 'composed-native-archive-fallback-v1'
export type ArchiveGroundFallback = { archiveSHA256: string; contract: string; records: {
  key: string; point: number[]; height: number; sourceLevels: number[]; ellipsoidZero: boolean
}[] }
export function composedGroundRevision(nativeRevision: string, fallback: ArchiveGroundFallback) {
  return createHash('sha256').update(JSON.stringify([COMPOSED_GROUND_POLICY, nativeRevision, fallback])).digest('hex')
}

export async function enrichComposedGround(features: Footprint[], native: GroundLayer, fallback: ArchiveGroundFallback) {
  if (!/^[a-f0-9]{64}$/.test(fallback.archiveSHA256) || fallback.contract !== 'resolved-ancestor-grid-v1') throw Error('Invalid archive provenance')
  const byKey = new Map(fallback.records.map(row => [row.key, row]))
  if (byKey.size !== fallback.records.length) throw Error('Duplicate fallback key')
  const heights: (number | undefined)[] = [], assignments: string[] = []
  const wasMissing = features.map(f => !Number.isFinite(f.z)), beforeMissing = wasMissing.filter(Boolean).length
  let source, preciseOverride = 0
  for (let start = 0; start < features.length; start += 1024) {
    const batch = features.slice(start, start + 1024)
    const sampled = await native.sample(batch.map(f => f.ring[0]!))
    if (sampled.source.fileSignature !== native.revision) throw Error('Composed DEM source changed')
    if (sampled.heights.length !== batch.length) throw Error('Invalid DEM result')
    source = sampled.source
    for (let i = 0; i < batch.length; i++) {
      const f = batch[i]!, value = sampled.heights[i], record = byKey.get(f.key)
      if (typeof value === 'number' && Number.isFinite(value) && value >= -500 && value <= 9000) {
        heights.push(value); assignments.push('composed')
        if (Number.isFinite(f.z) && f.z !== value) preciseOverride++
      } else if (record) {
        if (record.point.length !== 2 || record.point.some((v, k) => v !== f.ring[0]![k])) throw Error('Fallback anchor mismatch')
        if (record.ellipsoidZero || !record.sourceLevels.length || record.sourceLevels.some(l => !Number.isInteger(l) || l < 0 || l > 20)
          || !Number.isFinite(record.height) || record.height < -500 || record.height > 9000) throw Error('Archive fallback is unsupported')
        heights.push(record.height); assignments.push('archive-ancestor')
      } else { heights.push(undefined); assignments.push('missing') }
    }
  }
  await native.verify?.()
  features.forEach((f, i) => { f.z = heights[i] })
  const remaining = heights.filter(z => z === undefined).length
  return { policy: COMPOSED_GROUND_POLICY, fileSignature: composedGroundRevision(native.revision, fallback),
    priority: ['composed-native', 'verified-archive-ancestor'], source, assignments,
    archiveFallback: { archiveSHA256: fallback.archiveSHA256, contract: fallback.contract,
      records: fallback.records.filter(r => features.some((f, i) => f.key === r.key && assignments[i] === 'archive-ancestor')) },
    metrics: { beforeMissing, newlyFilled: wasMissing.filter((missing, i) => missing && heights[i] !== undefined).length, preciseOverride, remaining } }
}
