import { CELL_LAT, CELL_LON, CELL_RADIUS_M } from './context-cells'
import type { ContextReply } from './context-masses'
import { publishableGround } from './ground-publication'

export function groundCellKey(lat: number, lon: number, radius: number): string | undefined {
  const i = Math.floor(lat / CELL_LAT), j = Math.floor(lon / CELL_LON)
  return radius === CELL_RADIUS_M && Math.abs(lat - (i + .5) * CELL_LAT) < 1e-7
    && Math.abs(lon - (j + .5) * CELL_LON) < 1e-7 ? `${i}:${j}` : undefined
}

export function createPublishedGroundReader(get: (url: string) => Promise<Response> = url => fetch(url, { signal: AbortSignal.timeout(5000) }), now = Date.now) {
  const base = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/map-data/world-ground`
  type Index = { cells: Record<string, { file: string; sampledAt: string }> }
  let index: Promise<Index | null> | undefined, checkedAt = -Infinity
  const loaded = new Map<string, ContextReply>(), pending = new Map<string, Promise<ContextReply | undefined>>()
  return async (lat: number, lon: number, radius: number, detail: 'roads' | 'full'): Promise<ContextReply | undefined> => {
    const key = groundCellKey(lat, lon, radius)
    if (!key) return undefined
    if (!index || now() - checkedAt >= 60000) {
      checkedAt = now()
      index = get(`${base}/catalog.json`).then(async r => r.ok ? r.json() : null).catch(() => null)
    }
    const catalog = await index, entry = catalog?.cells?.[key]
    if (!entry || !/^[a-f0-9]{64}\.json$/.test(entry.file)
      || !Number.isFinite(Date.parse(entry.sampledAt)) || now() - Date.parse(entry.sampledAt) > 86400000) return undefined
    let reply = loaded.get(entry.file)
    if (!reply) {
      let task = pending.get(entry.file)
      if (!task) {
        task = get(`${base}/${entry.file}`).then(async r => {
          const value = r.ok ? await r.json() : null
          if (!publishableGround(value)) return undefined
          loaded.set(entry.file, value)
          while (loaded.size > 16) loaded.delete(loaded.keys().next().value!)
          return value as ContextReply
        }).catch(() => undefined).finally(() => pending.delete(entry.file))
        pending.set(entry.file, task)
      }
      reply = await task
    }
    if (!reply) return undefined
    const roads = reply.record?.roads as { revision?: unknown } | undefined
    if (detail === 'roads' && (typeof roads?.revision !== 'string' || !roads.revision)) return undefined
    const snapshot = { ...reply, displaySnapshot: { sampledAt: entry.sampledAt, expiresAt: Date.parse(entry.sampledAt) + 86400000 } }
    if (detail === 'full') return snapshot
    // The published full response's carriageways are the same source evidence;
    // preview/full share one file without drawing parcels during the preview.
    return { ...snapshot, features: { type: 'FeatureCollection',
      features: reply.features!.features.filter(f => f.properties?.layer === 'carriageway') } }
  }
}
