import { fetchContextGround, type ContextReply } from './context-masses'
import { readSceneCache, writeSceneCache } from './scene-cache'
import { createPublishedGroundReader } from './published-ground'

export type GroundDetail = 'roads' | 'full'
const cache = new Map<string, { reply: ContextReply; at: number }>()
const TTL = 10 * 60_000
const KEEP = 128
const publishedGround = createPublishedGroundReader()
const reusable = (reply: ContextReply | undefined): reply is ContextReply => reply?.status === 'ok' && !reply.gaps?.length
  && (!reply.displaySnapshot || Number.isFinite(reply.displaySnapshot.expiresAt) && Date.now() < reply.displaySnapshot.expiresAt)

async function untilAborted<T>(task: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return task
  signal.throwIfAborted()
  let abort: () => void = () => {}
  const cancelled = new Promise<never>((_resolve, reject) => {
    abort = () => reject(signal.reason)
    signal.addEventListener('abort', abort, { once: true })
  })
  try { return await Promise.race([task, cancelled]) }
  finally { signal.removeEventListener('abort', abort) }
}

/** Call after drawing the old fill, inside the existing bounded cell request. */
export async function refreshGroundBoundaries(lat: number, lon: number, radius: number, detail: GroundDetail,
  previous: ContextReply, signal?: AbortSignal): Promise<ContextReply | undefined> {
  signal?.throwIfAborted()
  const missing = (reply: ContextReply) => reply.features?.features.some(feature => feature.properties?.layer === 'ground'
    && !['LineString', 'MultiLineString', 'GeometryCollection'].includes(feature.properties?.parcel_boundary?.type))
  if (detail !== 'full' || !missing(previous)) return undefined
  const fresh = await untilAborted(fetchContextGround(lat, lon, radius, signal, 'full'), signal)
  signal?.throwIfAborted()
  if (!reusable(fresh) || missing(fresh)) return undefined
  const key = `${lat}/${lon}/${radius}/${detail}`
  cache.delete(key)
  cache.set(key, { reply: fresh, at: Date.now() })
  if (cache.size > KEEP) cache.delete(cache.keys().next().value!)
  void writeSceneCache('ground-local-roads-v2', key, fresh, KEEP)
  return fresh
}

export async function cachedGround(lat: number, lon: number, radius: number, detail: GroundDetail, signal?: AbortSignal): Promise<ContextReply> {
  signal?.throwIfAborted()
  const key = `${lat}/${lon}/${radius}/${detail}`
  const hit = cache.get(key)
  if (hit && Date.now() - hit.at < TTL && reusable(hit.reply)) {
    cache.delete(key)
    cache.set(key, hit)
    return hit.reply
  }
  const saved = await readSceneCache<ContextReply>('ground-local-roads-v2', key, TTL)
  signal?.throwIfAborted()
  const reply = reusable(saved) ? saved
    : await untilAborted(publishedGround(lat, lon, radius, detail), signal) ?? await fetchContextGround(lat, lon, radius, signal, detail)
  signal?.throwIfAborted()
  if (reply.status !== 'ok') throw new Error(reply.reason || 'Ground data unavailable')
  if (reusable(reply)) {
    cache.set(key, { reply, at: Date.now() })
    if (cache.size > KEEP) cache.delete(cache.keys().next().value!)
    if (!reusable(saved)) void writeSceneCache('ground-local-roads-v2', key, reply, KEEP)
  }
  return reply
}
