import type { ParcelSet } from '../lib/engine'

const PREFIX = 'site-map.startup.v1:'
const TTL = 24 * 60 * 60 * 1000

export function readStartupDrawing(key: string, storage?: Pick<Storage, 'getItem'>): (ParcelSet & { pnu?: string }) | null {
  try {
    storage ??= typeof window === 'undefined' ? undefined : window.sessionStorage
    const record = JSON.parse(storage?.getItem(PREFIX + key) ?? 'null')
    if (!record || Date.now() - record.at > TTL || !Array.isArray(record.drawn?.geometries)) return null
    return record.drawn
  } catch { return null }
}

export function writeStartupDrawing(key: string, drawn: ParcelSet, storage?: Pick<Storage, 'setItem'>) {
  if (!drawn.geometries.length || drawn.look !== 'saved') return
  try {
    storage ??= typeof window === 'undefined' ? undefined : window.sessionStorage
    storage?.setItem(PREFIX + key, JSON.stringify({ at: Date.now(), drawn }))
  } catch { /* Storage is optional; server restoration remains authoritative. */ }
}
