export function refreshGroundRoads(full: any, roads: any) {
  if (roads.status !== 'ok') throw new Error('Installed road source unavailable; retain previous snapshot')
  if (!roads.record?.roads?.revision || roads.features?.type !== 'FeatureCollection'
    || !Array.isArray(roads.features.features)) throw new Error('Invalid road source receipt')
  return { ...full, record: { ...full.record, roads: roads.record.roads },
    counts: { ...full.counts, carriageways: roads.counts?.carriageways ?? roads.features.features.length },
    gaps: [...(full.gaps || []).filter((gap: unknown) => typeof gap !== 'string' || !/^(roads|carriageways):/.test(gap)), ...(roads.gaps || [])],
    features: { type: 'FeatureCollection', features: [
      ...full.features.features.filter((f: any) => f.properties?.layer !== 'carriageway'),
      ...roads.features.features,
    ] } }
}
