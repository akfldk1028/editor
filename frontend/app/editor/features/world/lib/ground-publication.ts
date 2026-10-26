import type { ContextReply } from './context-masses'

// Missing installed road evidence is persistent coverage information, not an
// upstream outage. Keep usable cadastral/cover geometry and its explicit gaps.
export function publishableGround(value: ContextReply): boolean {
  const receipts = ['ground', 'cover'].every(kind => {
    const record = value?.record?.[kind] as { revision?: string; retrieved?: string; complete_bbox?: unknown[] } | undefined
    return record && /^[a-f0-9]{64}$/.test(record.revision ?? '') && Number.isFinite(Date.parse(record.retrieved ?? ''))
      && record.complete_bbox?.length === 4 && record.complete_bbox.every(Number.isFinite)
  })
  return value?.status === 'ok' && value.features?.type === 'FeatureCollection'
    && Array.isArray(value.features.features)
    && (!value.gaps?.length || receipts && Array.isArray(value.gaps) && value.gaps.every(gap => typeof gap === 'string' && (
      gap === 'roads: No installed road centrelines in this viewport; this does not establish absence of roads'
      || /^carriageways: \d+ centreline\(s\) without lanes left out$/.test(gap))))
}
